from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .engine import ManifestRow
from .profiles import ProfileConfig
from .safety import is_valid_filename


# DEFAULT RULES

DEFAULT_RULES = [
    # STAGE 1 AND 2: EXISTING MOVE RULES
    {"id": 1, "name": "Documents", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".pdf", ".docx", ".doc", ".pptx", ".txt", ".rtf", ".odt", ".md"]}',
     "destination_template": "{root}/Documents/{filename}", "action_type": "move"},
    {"id": 2, "name": "Photos", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff"]}',
     "destination_template": "{root}/Photos/{filename}", "action_type": "move"},
    {"id": 3, "name": "Music", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"]}',
     "destination_template": "{root}/Music/{filename}", "action_type": "move"},
    {"id": 4, "name": "Video", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]}',
     "destination_template": "{root}/Video/{filename}", "action_type": "move"},
    {"id": 5, "name": "Compressed", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]}',
     "destination_template": "{root}/Compressed/{filename}", "action_type": "move"},
    {"id": 6, "name": "Code", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".go", ".rs", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml"]}',
     "destination_template": "{root}/Code/{filename}", "action_type": "move"},
    {"id": 7, "name": "Installers", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".msi", ".exe", ".dmg", ".deb", ".rpm", ".apk"]}',
     "destination_template": "{root}/Installers/{filename}", "action_type": "move"},
    {"id": 8, "name": "Old files archive", "rule_type": "date", "enabled": True, "priority": 50,
     "rule_config": '{"older_than_days": 365}',
     "destination_template": "{root}/Archive/{date_year}/{filename}", "action_type": "move"},
    {"id": 9, "name": "Duplicate consolidation", "rule_type": "status", "enabled": True, "priority": 5,
     "rule_config": '{"status": "duplicate"}',
     "destination_template": "{root}/Duplicates/{filename}", "action_type": "move"},
    {"id": 10, "name": "Uncategorized", "rule_type": "always", "enabled": True, "priority": 100,
     "rule_config": "{}",
     "destination_template": "{root}/Other/{filename}", "action_type": "move"},
    {"id": 11, "name": "Spreadsheets", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".csv", ".xlsx", ".xls"]}',
     "destination_template": "{root}/Spreadsheets/{filename}", "action_type": "move"},
    # STAGE 4: DEFAULT RENAME RULES
    {"id": 12, "name": "Rename docs by title", "rule_type": "extension", "enabled": True, "priority": 20,
     "rule_config": '{"extensions": [".pdf", ".docx"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{date_iso}_{doc_type}_{title_sanitized}.{extension}"},
    {"id": 14, "name": "Year prefix screenshots", "rule_type": "folder", "enabled": True, "priority": 20,
     "rule_config": '{"folders": ["screenshots", "Screenshots", "screen_shots"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{date_year}_Screenshot_{filename}"},
    {"id": 13, "name": "Date prefix photos", "rule_type": "extension", "enabled": True, "priority": 20,
     "rule_config": '{"extensions": [".jpg", ".jpeg", ".png", ".gif", ".heic"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{date_iso}_{filename}"},
    {"id": 16, "name": "Date prefix reports", "rule_type": "extension", "enabled": True, "priority": 20,
     "rule_config": '{"extensions": [".xlsx", ".csv"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{date_iso}_{doc_type}_{stem}.{extension}"},
    {"id": 15, "name": "Docs move and rename by title", "rule_type": "extension", "enabled": True, "priority": 15,
     "rule_config": '{"extensions": [".pdf", ".docx", ".txt", ".md"]}',
     "destination_template": "{root}/Documents/{date_iso}_{doc_type}_{title_sanitized}.{extension}",
     "action_type": "move+rename", "rename_template": "{date_iso}_{doc_type}_{title_sanitized}.{extension}"},
    # STAGE 4 EXTENSION: NORMALIZATION RENAME RULES
    {"id": 17, "name": "Lowercase text files", "rule_type": "extension", "enabled": True, "priority": 25,
     "rule_config": '{"extensions": [".txt", ".md"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{stem_lower}.{extension}"},
    {"id": 18, "name": "Replace spaces with hyphens", "rule_type": "pattern", "enabled": True, "priority": 30,
     "rule_config": '{"patterns": ["* *"]}',
     "destination_template": "", "action_type": "rename",
     "rename_template": "{filename_nospace}"},
]


@dataclass
class RuleMatch:
    # REPRESENTS A SINGLE RULE MATCH RESULT WITH THE PROPOSED ACTION DETAILS
    original_path: str
    proposed_path: str
    action_type: str
    rule_id: int | None = None
    reason: str = ""
    # STAGE 4: RENAME SPECIFIC FIELDS
    original_filename: str = ""
    new_filename: str = ""


class RulesEngine:
    # DETERMINISTIC RULES ENGINE THAT PROPOSES FILE ACTIONS WITHOUT AI
    # APPLIES EXTENSION PATTERN DATE SIZE AND FOLDER BASED RULES IN PRIORITY ORDER
    # NOW SUPPORTS RENAME AND MOVE AND RENAME ACTION TYPES

    def __init__(self, profile: ProfileConfig, scan_root: str = "") -> None:
        self.profile = profile
        self.scan_root = scan_root.rstrip("/").rstrip("\\")

    def evaluate(self, manifest_rows: list[ManifestRow], rules: list[dict]) -> list[RuleMatch]:
        # EVALUATES ALL ENABLED RULES AGAINST EVERY MANIFEST ROW AND COLLECTS MATCHES
        # PRE PARSE ALL RULE CONFIGS ONCE TO AVOID PER ROW JSON PARSING
        # WORK ON COPIES TO AVOID MUTATING CALLER RULE DICTS
        prepared_rules: list[dict] = []
        for rule in rules:
            prepared = dict(rule)
            if isinstance(prepared.get("rule_config"), str):
                try:
                    prepared["_parsed_config"] = json.loads(prepared["rule_config"])
                except (json.JSONDecodeError, TypeError):
                    prepared["_parsed_config"] = {}
            else:
                prepared["_parsed_config"] = prepared.get("rule_config", {})
            # PRE COMPILE EXTENSION SETS FOR PERFORMANCE
            config = prepared["_parsed_config"]
            if "extensions" in config:
                prepared["_compiled_extensions"] = {
                    ext.lower() for ext in config["extensions"]
                }
            prepared_rules.append(prepared)
        sorted_rules = sorted(prepared_rules, key=lambda r: r.get("priority", 0))
        profile_excluded = set(self.profile.excluded_folders) if self.profile else set()
        profile_included = self.profile.included_folders if self.profile else []
        # DETERMINE NAMING STRATEGY FROM PROFILE
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
        # NORMALIZATION PASS: APPLY RULES WITH PRIORITY >= 25 TO EXISTING MATCHES
        # SO THAT NORMALIZATION (LOWERCASE REPLACE SPACES) APPLIES EVEN TO FILES
        # ALREADY CAUGHT BY HIGHER PRIORITY CONTENT RULES
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
        # NLP OVERRIDE PASS: APPLY NLP-GENERATED FILENAMES/DESTINATIONS TO MATCHES
        # WITH HIGH CONFIDENCE (CONFIDENCE >= PROFILE THRESHOLD)
        if self.profile:
            nlp_threshold = self.profile.nlp_confidence_threshold
        else:
            nlp_threshold = 0.0
        nlp_override_count = 0
        # NLP OVERRIDE AND STANDALONE PASSES: ONLY RUN FOR NLP-ENABLED STRATEGIES
        if strategy in ("nlp_enhanced", "nlp_only"):
            for match in matches:
                original_row = next((r for r in manifest_rows if r.path == match.original_path), None)
                if original_row is None or original_row.nlp_confidence <= nlp_threshold:
                    continue
                nlp_filename = original_row.smart_filename
                if not nlp_filename:
                    nlp_filename = self._render_rename(original_row, "{nlp_topic}_{nlp_author}_{nlp_date}.{extension}")
                nlp_override = False
                if nlp_filename and nlp_filename != match.new_filename:
                    nlp_override = True
                    match.new_filename = nlp_filename
                    if match.action_type in ("rename",):
                        match.proposed_path = str(Path(match.original_path).parent / nlp_filename).replace("\\", "/")
                        match.reason += " | NLP-enhanced rename"
                    elif match.action_type in ("move", "move+rename"):
                        move_parent = str(Path(match.proposed_path).parent).replace("\\", "/")
                        match.proposed_path = f"{move_parent}/{nlp_filename}"
                        if match.action_type == "move":
                            match.action_type = "move+rename"
                        match.reason += " | NLP-enhanced filename"
                nlp_destination = original_row.smart_destination
                if nlp_destination and match.action_type in ("move", "move+rename"):
                    nlp_override = True
                    match.proposed_path = f"{nlp_destination.rstrip('/')}/{nlp_filename or match.new_filename}"
                    match.action_type = "move+rename"
                    match.reason += " | NLP-enhanced destination"
                if nlp_override:
                    nlp_override_count += 1
            # NLP STANDALONE PASS: CREATE NEW RENAME ACTIONS FOR HIGH-CONFIDENCE FILES
            # THAT WERE NOT MATCHED BY ANY RULE
            # REQUIRE AT LEAST MINIMAL CONFIDENCE (0.1) TO AVOID NONSENSICAL RENAMES OF
            # EMPTY/BINARY FILES WITH NO EXTRACTED CONTENT.
            _NLP_MIN_CONFIDENCE = 0.1
            matched_original_paths = {m.original_path for m in matches}
            for row in manifest_rows:
                if row.path in matched_original_paths:
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
                nlp_override_count += 1
        # COLLISION DETECTION: CHECK EACH PROPOSED RENAME AGAINST OTHER SCANNED FILES
        # AND EXISTING FILESYSTEM TO SHOW THE ACTUAL DESTINATION PATH IN PREVIEW
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

    def _rule_matches(self, row: ManifestRow, rule: dict) -> bool:
        # CHECKS WHETHER A SINGLE RULE MATCHES A MANIFEST ROW BASED ON ITS TYPE AND CONFIG
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
        # CHECKS WHETHER THE FILE EXTENSION IS IN THE RULE EXTENSION LIST
        allowed = rule.get("_compiled_extensions")
        if allowed is not None:
            return row.extension.lower() in allowed
        config = rule.get("_parsed_config", {})
        return row.extension.lower() in {e.lower() for e in config.get("extensions", [])}

    def _glob_or_regex_match(self, target: str, patterns: list[str]) -> bool:
        """Match target against patterns supporting both glob (*?) and regex syntax."""
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
        """Check whether the filename matches any of the rule patterns."""
        config = rule.get("_parsed_config", {})
        return self._glob_or_regex_match(Path(row.path).name, config.get("patterns", []))

    def _matches_date(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE MODIFICATION DATE FALLS WITHIN THE RULE DATE RANGE
        if not row.modified_at:
            return False
        try:
            file_date = datetime.fromisoformat(row.modified_at)
            # CONVERT TIMEZONE AWARE DATES TO LOCAL TIME BEFORE STRIPPING TIMEZONE
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
        # CHECKS WHETHER THE FILE SIZE FALLS WITHIN THE RULE MIN MAX SIZE RANGE
        min_bytes = config.get("min_bytes") or 0
        max_bytes = config.get("max_bytes")
        if max_bytes is None or max_bytes == "":
            max_bytes = float("inf")
        return min_bytes <= row.size <= max_bytes

    def _matches_folder(self, row: ManifestRow, rule: dict) -> bool:
        """Check whether the file folder path matches any of the rule folder patterns."""
        config = rule.get("_parsed_config", {})
        if self._glob_or_regex_match(Path(row.folder_path).name, config.get("folders", [])):
            return True
        return self._glob_or_regex_match(row.folder_path, config.get("folders", []))

    def _matches_status(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE STATUS MATCHES THE RULE REQUIRED STATUS VALUE
        return row.status == config.get("status", "")

    def _apply_rule(self, row: ManifestRow, rule: dict) -> RuleMatch | None:
        # APPLIES A MATCHING RULE AND RETURNS A RULE MATCH WITH THE PROPOSED ACTION
        # HANDLES MOVE RENAME AND MOVE AND RENAME ACTION TYPES
        action_type = rule.get("action_type", "move")
        original_filename = Path(row.path).name
        if action_type == "rename":
            # RENAME ONLY: RENDER NEW FILENAME IN THE SAME DIRECTORY
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
            # MOVE AND RENAME: RENDER BOTH DESTINATION AND NEW FILENAME
            destination_template = rule.get("destination_template", "")
            rename_template = rule.get("rename_template", "")
            if not destination_template:
                return None
            proposed_path = self._render_destination(row, destination_template)
            new_filename = self._render_rename(row, rename_template) if rename_template else original_filename
            # APPLY THE RENAME TO THE DESTINATION PATH SO THE FILE ACTUALLY GETS RENAMED
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
        # DEFAULT: MOVE ONLY
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
        # RENDERS A DESTINATION PATH TEMPLATE BY SUBSTITUTING FILE METADATA PLACEHOLDERS
        # SUPPORTS ALL 14 TEMPLATE VARIABLES INCLUDING STAGE 4 ADDITIONS
        result = self._substitute_variables(row, template)
        # PREVENT PATH TRAVERSAL: ENSURE THE RESULT STAYS WITHIN THE SCAN ROOT
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
        # RENDERS A FILENAME ONLY TEMPLATE BY SUBSTITUTING FILE METADATA PLACEHOLDERS
        # STRIPS DIRECTORY COMPONENTS FROM THE RESULT TO PREVENT DIRECTORY TRAVERSAL
        # VALIDATES OS FILENAME CONSTRAINTS AND SANITIZES IF NEEDED
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
        # SHARED TEMPLATE VARIABLE SUBSTITUTION USED BY BOTH DESTINATION AND RENAME RENDERING
        filename = Path(row.path).name
        stem = Path(row.path).stem
        extension = row.extension
        folder = row.folder_path
        title = row.suggested_title or stem
        title_sanitized = re.sub(r'[<>:"/\\|?*]', "-", title).strip(" .-") or "Untitled"

        result = template

        # FILENAME IDENTITY VARIABLES
        result = result.replace("{filename}", filename)
        result = result.replace("{stem}", stem)
        result = result.replace("{extension}", extension.lstrip("."))
        result = result.replace("{folder}", folder)
        result = result.replace("{root}", self.scan_root)

        # TITLE VARIABLES
        result = result.replace("{title}", title)
        result = result.replace("{title_sanitized}", title_sanitized)

        # DATE VARIABLES
        result = result.replace("{date_year}", row.modified_at[:4] if row.modified_at and len(row.modified_at) >= 4 else "unknown")
        result = result.replace("{date_iso}", row.date_iso if row.date_iso else "unknown")
        result = result.replace("{date_month}", row.date_month if row.date_month else "unknown")
        result = result.replace("{date_day}", row.date_day if row.date_day else "unknown")
        result = result.replace("{date_full}", row.date_full if row.date_full else "unknown")

        # SIZE VARIABLES
        result = result.replace("{size_kb}", str(row.size_kb) if row.size_kb else "0")
        result = result.replace("{size_mb}", str(row.size_mb) if row.size_mb else "0")

        # NORMALIZATION VARIABLES
        result = result.replace("{stem_lower}", stem.lower())
        result = result.replace("{ext_lower}", extension.lstrip(".").lower())
        result = result.replace("{filename_lower}", filename.lower())
        result = result.replace("{filename_nospace}", filename.replace(" ", "-").replace("_", "-"))
        result = result.replace("{stem_nospace}", stem.replace(" ", "-").replace("_", "-"))

        # DOCUMENT TYPE VARIABLES
        result = result.replace("{doc_type}", row.doc_type if row.doc_type else "Document")
        result = result.replace("{doc_type_lower}", (row.doc_type if row.doc_type else "document").lower())

        # NLP VARIABLES
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
