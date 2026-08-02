from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..engine import ManifestRow
from ..extractors import _get_category, is_no_rename
from ..profiles import ProfileConfig
from ..core.safety import is_valid_filename


@dataclass
class RuleMatch:
    original_path: str = ""
    proposed_path: str = ""
    action_type: str = ""
    rule_id: int | None = None
    reason: str = ""
    original_filename: str = ""
    new_filename: str = ""


class RulesEngine:

    def __init__(self, profile: ProfileConfig, scan_root: str = "", llm_engine=None) -> None:
        self.profile = profile
        self.scan_root = scan_root.rstrip("/").rstrip("\\")
        self._refiner = None
        if llm_engine is not None and getattr(llm_engine, "config", None) and llm_engine.config.enabled:
            from ..llm.refine import RefineEngine
            self._refiner = RefineEngine(llm_engine, self.scan_root)

    def evaluate(self, manifest_rows: list[ManifestRow], rules: list[dict]) -> list[RuleMatch]:
        prepared_rules: list[dict] = []
        for rule in rules:
            prepared = dict(rule)
            raw = prepared.get("rule_config", {})
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    while isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    prepared["_parsed_config"] = parsed
                except (json.JSONDecodeError, TypeError):
                    prepared["_parsed_config"] = {}
            else:
                prepared["_parsed_config"] = raw
            config = prepared["_parsed_config"]
            if "extensions" in config:
                prepared["_compiled_extensions"] = {
                    ext.lower() for ext in config["extensions"]
                }
            prepared_rules.append(prepared)
        sorted_rules = sorted(prepared_rules, key=lambda r: r.get("priority", 0))
        profile_excluded = set(self.profile.excluded_folders) if self.profile else set()
        profile_included = self.profile.included_folders if self.profile else []
        strategy = self.profile.naming_strategy if self.profile else "nlp_enhanced"
        matches: list[RuleMatch] = []
        if strategy in ("nlp_enhanced", "rule_based"):
            for row in manifest_rows:
                if row.status in {"unreadable", "protected"}:
                    continue
                if profile_excluded and any(
                    row.folder_path.replace("\\", "/") == ex.replace("\\", "/").rstrip("/")
                    or row.folder_path.replace("\\", "/").startswith(ex.replace("\\", "/").rstrip("/") + "/")
                    for ex in profile_excluded
                ):
                    continue
                if profile_included and not any(
                    row.folder_path.replace("\\", "/") == inc.replace("\\", "/").rstrip("/")
                    or row.folder_path.replace("\\", "/").startswith(inc.replace("\\", "/").rstrip("/") + "/")
                    for inc in profile_included
                ):
                    continue
                for rule in sorted_rules:
                    if not rule.get("enabled", True):
                        continue
                    if self._rule_matches(row, rule):
                        match = self._apply_rule(row, rule)
                        if match is not None:
                            if Path(match.proposed_path) != Path(match.original_path):
                                matches.append(match)
                                break
        if strategy in ("nlp_enhanced", "rule_based"):
            normalization_rules = [r for r in sorted_rules if r.get("enabled", True) and r.get("priority", 0) >= 25]
            if normalization_rules:
                match_lookup = {m.original_path: m for m in matches}
                for row in manifest_rows:
                    match = match_lookup.get(row.path)
                    if match is None:
                        continue
                    for rule in normalization_rules:
                        if not self._rule_matches(row, rule):
                            continue
                        if is_no_rename(row.extension):
                            continue
                        rename_tpl = rule.get("rename_template", "")
                        if not rename_tpl:
                            continue
                        new_filename = self._render_rename(row, rename_tpl)
                        if new_filename and new_filename != Path(match.proposed_path).name:
                            match.new_filename = new_filename
                            if match.action_type == "rename":
                                match.proposed_path = str(Path(match.original_path).parent / new_filename).replace("\\", "/")
                            else:
                                move_parent = str(Path(match.proposed_path).parent).replace("\\", "/")
                                match.proposed_path = f"{move_parent}/{new_filename}"
                            break
        if self.profile:
            nlp_threshold = self.profile.nlp_confidence_threshold
        else:
            nlp_threshold = 0.0
        if strategy == "nlp_enhanced":
            pairs: list[tuple[RuleMatch, ManifestRow]] = []
            for match in matches:
                original_row = next((r for r in manifest_rows if r.path == match.original_path), None)
                if original_row is None:
                    continue
                pairs.append((match, original_row))
            # Deterministic content-based grouping for document batches: related
            # documents (shared source folder) are co-located under ONE destination
            # folder (Documents/{doc_type}/{batch_label}/) instead of each file
            # spawning its own deep subfolder. Non-document files keep the existing
            # per-file smart destination (with year subfolders intact).
            doc_pairs: list[tuple[RuleMatch, ManifestRow]] = []
            other_pairs: list[tuple[RuleMatch, ManifestRow]] = []
            for match, original_row in pairs:
                if _get_category(original_row.extension) == "document":
                    doc_pairs.append((match, original_row))
                else:
                    other_pairs.append((match, original_row))
            self._co_locate_document_batches(doc_pairs, nlp_threshold)
            if self._refiner is not None:
                self._refiner.refine_matches(other_pairs, locked_pairs=doc_pairs)
            else:
                for match, original_row in other_pairs:
                    if is_no_rename(original_row.extension):
                        continue
                    if original_row.nlp_confidence <= nlp_threshold:
                        continue
                    base = Path(match.proposed_path).parent
                    nlp_filename = original_row.smart_filename
                    if not nlp_filename:
                        nlp_filename = self._render_rename(
                            original_row, "{nlp_topic}_{nlp_author}.{extension}"
                        )
                    nlp_destination = original_row.smart_destination
                    if nlp_destination:
                        sub_parts = [
                            p for p in nlp_destination.replace("\\", "/").strip("/").split("/") if p
                        ]
                        if sub_parts and sub_parts[0].lower() == base.name.lower():
                            sub_parts = sub_parts[1:]
                        base = base.joinpath(*sub_parts)
                    new_filename = nlp_filename or Path(match.proposed_path).name
                    target = base / new_filename
                    new_path = str(target).replace("\\", "/")
                    if new_path == match.proposed_path:
                        continue
                    if match.action_type == "move" and new_filename != match.original_filename:
                        match.action_type = "move+rename"
                    elif match.action_type == "rename" and sub_parts:
                        match.action_type = "move+rename"
                    match.new_filename = new_filename
                    match.proposed_path = new_path
                    match.reason += " | NLP-enhanced destination"
        if strategy in ("nlp_only",) or (strategy == "nlp_enhanced" and self._refiner is None):
            _NLP_MIN_CONFIDENCE = 0.1
            matched_original_paths = {m.original_path for m in matches}
            for row in manifest_rows:
                if row.path in matched_original_paths:
                    continue
                if is_no_rename(row.extension):
                    continue
                if row.nlp_confidence <= nlp_threshold or row.nlp_confidence < _NLP_MIN_CONFIDENCE:
                    continue
                nlp_filename = row.smart_filename
                if not nlp_filename:
                    continue
                original_basename = Path(row.path).name
                if nlp_filename == original_basename:
                    continue
                proposed = str(Path(row.path).parent / nlp_filename).replace("\\", "/")
                matches.append(RuleMatch(
                    original_path=row.path,
                    proposed_path=proposed,
                    action_type="rename",
                    rule_id=None,
                    reason="NLP-generated rename",
                    original_filename=original_basename,
                    new_filename=nlp_filename,
                ))
        existing_for_collision: set[str] = set()
        for row in manifest_rows:
            existing_for_collision.add(row.path)
        for match in matches:
            if match.action_type in {"rename", "move+rename"}:
                proposed = Path(match.proposed_path)
                if proposed.exists() or str(proposed) in existing_for_collision:
                    counter = 2
                    while True:
                        candidate = proposed.parent / f"{proposed.stem} ({counter}){proposed.suffix}"
                        candidate_str = str(candidate)
                        if not candidate.exists() and candidate_str not in existing_for_collision:
                            match.proposed_path = candidate_str.replace("\\", "/")
                            match.new_filename = candidate.name
                            break
                        counter += 1
                else:
                    existing_for_collision.add(match.proposed_path)
        return matches

    @staticmethod
    def _batch_key(row: ManifestRow) -> str:
        rel = (row.relative_path or "").replace("\\", "/")
        parent = Path(rel).parent.as_posix()
        return "" if parent in (".", "", "/") else parent

    @staticmethod
    def _sanitize_label(label: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]+', " ", label)
        safe = re.sub(r"\s+", "-", safe).strip(" .-_")
        return (safe.lower() or "documents")[:60]

    @staticmethod
    def _mode(values: list[str]) -> str:
        if not values:
            return ""
        return max(set(values), key=values.count)

    def _co_locate_document_batches(
        self, doc_pairs: list[tuple[RuleMatch, ManifestRow]], nlp_threshold: float
    ) -> None:
        from collections import defaultdict

        groups: dict[str, list[tuple[RuleMatch, ManifestRow]]] = defaultdict(list)
        order: list[str] = []
        for match, row in doc_pairs:
            key = self._batch_key(row)
            if key not in groups:
                order.append(key)
            groups[key].append((match, row))
        for key in order:
            active = [
                (m, r) for m, r in groups[key]
                if not is_no_rename(r.extension) and r.nlp_confidence > nlp_threshold
            ]
            if not active:
                continue
            if self.scan_root:
                root = Path(self.scan_root)
                direct_children = [
                    Path(match.proposed_path).parent
                    for match, _row in active
                    if Path(match.proposed_path).parent.parent == root
                ]
                base = direct_children[0] if direct_children else root / "Documents"
            else:
                base = Path(active[0][0].proposed_path).parent
            doc_types = [r.doc_type for _m, r in active if r.doc_type]
            doc_type = self._sanitize_label(self._mode(doc_types) or "Document")
            if key:
                batch_label = self._sanitize_label(Path(key).name)
            else:
                entities = [
                    e for _m, r in active
                    for e in (r.nlp_organization, r.nlp_project, r.nlp_topic) if e
                ]
                batch_label = self._sanitize_label(self._mode(entities)) if entities else ""
            target_dir = base.joinpath(doc_type)
            if batch_label:
                target_dir = target_dir.joinpath(batch_label)
            for match, row in active:
                nlp_filename = row.smart_filename
                if not nlp_filename:
                    nlp_filename = self._render_rename(row, "{nlp_topic}_{nlp_author}.{extension}")
                new_filename = nlp_filename or Path(match.proposed_path).name
                target = target_dir / new_filename
                new_path = str(target).replace("\\", "/")
                if new_path == match.proposed_path:
                    continue
                if match.action_type == "move" and new_filename != match.original_filename:
                    match.action_type = "move+rename"
                elif match.action_type == "rename":
                    match.action_type = "move+rename"
                match.new_filename = new_filename
                match.proposed_path = new_path
                match.reason += " | NLP-enhanced destination"

    def _rule_matches(self, row: ManifestRow, rule: dict) -> bool:
        rule_type = rule.get("rule_type", "")
        config = rule.get("_parsed_config", {})
        if rule_type == "extension":
            return self._matches_extension(row, rule)
        if rule_type == "pattern":
            return self._matches_pattern(row, rule)
        if rule_type == "date":
            return self._matches_date(row, config)
        if rule_type == "size":
            return self._matches_size(row, config)
        if rule_type == "folder":
            return self._matches_folder(row, rule)
        if rule_type == "status":
            return self._matches_status(row, config)
        if rule_type == "always":
            return True
        return False

    def _matches_extension(self, row: ManifestRow, rule: dict) -> bool:
        allowed = rule.get("_compiled_extensions")
        if allowed is not None:
            return row.extension.lower() in allowed
        config = rule.get("_parsed_config", {})
        return row.extension.lower() in {e.lower() for e in config.get("extensions", [])}

    def _glob_or_regex_match(self, target: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            has_glob = any(c in pattern for c in ("*", "?"))
            has_regex = bool(set("^$()+{}|\\[]") & set(pattern))
            if has_glob and not has_regex:
                if fnmatch.fnmatch(target, pattern):
                    return True
            else:
                try:
                    if re.search(pattern, target, re.IGNORECASE):
                        return True
                except re.error:
                    pass
        return False

    def _matches_pattern(self, row: ManifestRow, rule: dict) -> bool:
        config = rule.get("_parsed_config", {})
        return self._glob_or_regex_match(Path(row.path).name, config.get("patterns", []))

    def _matches_date(self, row: ManifestRow, config: dict) -> bool:
        if not row.modified_at:
            return False
        try:
            file_date = datetime.fromisoformat(row.modified_at)
            if file_date.tzinfo is not None:
                file_date = file_date.astimezone().replace(tzinfo=None)
        except ValueError:
            return False
        older_than_days = config.get("older_than_days")
        newer_than_days = config.get("newer_than_days")
        now = datetime.now()
        if older_than_days is not None:
            if (now - file_date).days < older_than_days:
                return False
        if newer_than_days is not None:
            if (now - file_date).days > newer_than_days:
                return False
        return True

    def _matches_size(self, row: ManifestRow, config: dict) -> bool:
        min_bytes = config.get("min_bytes") or 0
        max_bytes = config.get("max_bytes")
        if max_bytes is None or max_bytes == "":
            max_bytes = float("inf")
        return min_bytes <= row.size <= max_bytes

    def _matches_folder(self, row: ManifestRow, rule: dict) -> bool:
        config = rule.get("_parsed_config", {})
        if self._glob_or_regex_match(Path(row.folder_path).name, config.get("folders", [])):
            return True
        return self._glob_or_regex_match(row.folder_path, config.get("folders", []))

    def _matches_status(self, row: ManifestRow, config: dict) -> bool:
        return row.status == config.get("status", "")

    def _apply_rule(self, row: ManifestRow, rule: dict) -> RuleMatch | None:
        action_type = rule.get("action_type", "move")
        original_filename = Path(row.path).name
        if action_type == "rename":
            if is_no_rename(row.extension):
                return None
            rename_template = rule.get("rename_template", "")
            if not rename_template:
                return None
            new_filename = self._render_rename(row, rename_template)
            if not new_filename or new_filename == original_filename:
                return None
            proposed_path = str(Path(row.path).parent / new_filename).replace("\\", "/")
            return RuleMatch(
                original_path=row.path,
                proposed_path=proposed_path,
                action_type=action_type,
                rule_id=rule.get("id"),
                reason=f"Matched rule '{rule.get('name', 'unknown')}' ({rule.get('rule_type', 'unknown')})",
                original_filename=original_filename,
                new_filename=new_filename,
            )
        if action_type == "move+rename":
            destination_template = rule.get("destination_template", "")
            rename_template = rule.get("rename_template", "")
            if not destination_template:
                return None
            proposed_path = self._render_destination(row, destination_template)
            new_filename = self._render_rename(row, rename_template) if rename_template else original_filename
            if is_no_rename(row.extension):
                new_filename = original_filename
            if new_filename and new_filename != original_filename:
                proposed_path = str(Path(proposed_path).parent / new_filename).replace("\\", "/")
            return RuleMatch(
                original_path=row.path,
                proposed_path=proposed_path,
                action_type=action_type,
                rule_id=rule.get("id"),
                reason=f"Matched rule '{rule.get('name', 'unknown')}' ({rule.get('rule_type', 'unknown')})",
                original_filename=original_filename,
                new_filename=new_filename,
            )
        destination_template = rule.get("destination_template", "")
        if not destination_template:
            return None
        proposed_path = self._render_destination(row, destination_template)
        return RuleMatch(
            original_path=row.path,
            proposed_path=proposed_path,
            action_type=action_type,
            rule_id=rule.get("id"),
            reason=f"Matched rule '{rule.get('name', 'unknown')}' ({rule.get('rule_type', 'unknown')})",
            original_filename=original_filename,
            new_filename=Path(proposed_path).name if proposed_path else "",
        )

    def _render_destination(self, row: ManifestRow, template: str) -> str:
        result = self._substitute_variables(row, template)
        if self.scan_root:
            try:
                resolved = Path(result).resolve()
                scan_root_resolved = Path(self.scan_root).resolve()
                if not resolved.is_relative_to(scan_root_resolved):
                    return row.path
            except (ValueError, OSError):
                return row.path
        return result

    def _render_rename(self, row: ManifestRow, template: str) -> str:
        result = self._substitute_variables(row, template)
        result = Path(result).name
        valid, _reason = is_valid_filename(result)
        if not valid:
            safe_name = re.sub(r'[<>:"/\\|?*]', "-", result).strip(" .-")
            safe_name = safe_name[:250]
            stem, ext = Path(safe_name).stem, Path(safe_name).suffix or Path(result).suffix
            result = f"{stem}{ext}"
        return result

    def _substitute_variables(self, row: ManifestRow, template: str) -> str:
        filename = Path(row.path).name
        stem = Path(row.path).stem
        extension = row.extension
        folder = row.folder_path
        title = row.suggested_title or stem
        title_sanitized = re.sub(r'[<>:"/\\|?*]', "-", title).strip(" .-") or "Untitled"

        result = template

        result = result.replace("{filename}", filename)
        result = result.replace("{stem}", stem)
        result = result.replace("{extension}", extension.lstrip("."))
        result = result.replace("{folder}", folder)
        result = result.replace("{root}", self.scan_root)

        result = result.replace("{title}", title)
        result = result.replace("{title_sanitized}", title_sanitized)

        result = result.replace("{date_year}", row.modified_at[:4] if row.modified_at and len(row.modified_at) >= 4 else "unknown")
        result = result.replace("{date_iso}", row.date_iso if row.date_iso else "unknown")
        result = result.replace("{date_month}", row.date_month if row.date_month else "unknown")
        result = result.replace("{date_day}", row.date_day if row.date_day else "unknown")
        result = result.replace("{date_full}", row.date_full if row.date_full else "unknown")

        result = result.replace("{size_kb}", str(row.size_kb) if row.size_kb else "0")
        result = result.replace("{size_mb}", str(row.size_mb) if row.size_mb else "0")

        result = result.replace("{stem_lower}", stem.lower())
        result = result.replace("{ext_lower}", extension.lstrip(".").lower())
        result = result.replace("{filename_lower}", filename.lower())
        result = result.replace("{filename_nospace}", filename.replace(" ", "-").replace("_", "-"))
        result = result.replace("{stem_nospace}", stem.replace(" ", "-").replace("_", "-"))

        result = result.replace("{doc_type}", row.doc_type if row.doc_type else "Document")
        result = result.replace("{doc_type_lower}", (row.doc_type if row.doc_type else "document").lower())

        result = result.replace("{nlp_topic}", row.nlp_topic if row.nlp_topic else stem)
        result = result.replace("{nlp_author}", row.nlp_author if row.nlp_author else "Unknown")
        result = result.replace("{nlp_organization}", row.nlp_organization if row.nlp_organization else "Unknown")
        result = result.replace("{nlp_project}", row.nlp_project if row.nlp_project else "Unknown")
        result = result.replace("{nlp_summary}", row.nlp_summary if row.nlp_summary else "")
        result = result.replace("{nlp_confidence}", f"{row.nlp_confidence:.2f}" if row.nlp_confidence else "0.00")
        result = result.replace("{nlp_date}", row.nlp_date if row.nlp_date else row.date_iso if row.date_iso else "unknown")
        result = result.replace("{nlp_location}", row.nlp_location if row.nlp_location else "Unknown")
        result = result.replace("{nlp_camera}", row.nlp_camera if row.nlp_camera else "Unknown")
        result = result.replace("{nlp_artist}", row.nlp_artist if row.nlp_artist else "Unknown")
        result = result.replace("{nlp_album}", row.nlp_album if row.nlp_album else "Unknown")
        result = result.replace("{nlp_doc_type}", row.doc_type if row.doc_type else "Document")

        return result
