from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .engine import ManifestRow
from .profiles import ProfileConfig


@dataclass
class RuleMatch:
    # REPRESENTS A SINGLE RULE MATCH RESULT WITH THE PROPOSED ACTION DETAILS.
    original_path: str
    proposed_path: str
    action_type: str
    rule_id: int | None = None
    reason: str = ""


class RulesEngine:
    # DETERMINISTIC RULES ENGINE THAT PROPOSES FILE ACTIONS WITHOUT AI.
    # APPLIES EXTENSION, PATTERN, DATE, SIZE, AND FOLDER-BASED RULES IN PRIORITY ORDER.

    def __init__(self, profile: ProfileConfig, scan_root: str = "") -> None:
        self.profile = profile
        self.scan_root = scan_root.rstrip("/").rstrip("\\")

    def evaluate(self, manifest_rows: list[ManifestRow], rules: list[dict]) -> list[RuleMatch]:
        # EVALUATES ALL ENABLED RULES AGAINST EVERY MANIFEST ROW AND COLLECTS MATCHES.
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0))
        # PRE-PARSE ALL RULE CONFIGS ONCE TO AVOID PER-ROW JSON PARSING.
        for rule in sorted_rules:
            if isinstance(rule.get("rule_config"), str):
                rule["_parsed_config"] = json.loads(rule["rule_config"])
            else:
                rule["_parsed_config"] = rule.get("rule_config", {})
        profile_excluded = set(self.profile.excluded_folders) if self.profile else set()
        profile_included = self.profile.included_folders if self.profile else []
        matches: list[RuleMatch] = []
        for row in manifest_rows:
            if row.status in {"unreadable", "protected"}:
                continue
            if profile_excluded and any(row.folder_path.startswith(ex) for ex in profile_excluded):
                continue
            if profile_included and not any(row.folder_path.startswith(inc) for inc in profile_included):
                continue
            for rule in sorted_rules:
                if not rule.get("enabled", True):
                    continue
                if self._rule_matches(row, rule):
                    match = self._apply_rule(row, rule)
                    if match is not None:
                        if match.proposed_path != match.original_path:
                            matches.append(match)
                        break
        return matches

    def _rule_matches(self, row: ManifestRow, rule: dict) -> bool:
        # CHECKS WHETHER A SINGLE RULE MATCHES A MANIFEST ROW BASED ON ITS TYPE AND CONFIG.
        rule_type = rule.get("rule_type", "")
        config = rule.get("_parsed_config", {})
        if rule_type == "extension":
            return self._matches_extension(row, config)
        if rule_type == "pattern":
            return self._matches_pattern(row, config)
        if rule_type == "date":
            return self._matches_date(row, config)
        if rule_type == "size":
            return self._matches_size(row, config)
        if rule_type == "folder":
            return self._matches_folder(row, config)
        if rule_type == "status":
            return self._matches_status(row, config)
        if rule_type == "always":
            return True
        return False

    def _matches_extension(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE EXTENSION IS IN THE RULE'S EXTENSION LIST.
        allowed_extensions = [ext.lower() for ext in config.get("extensions", [])]
        return row.extension.lower() in allowed_extensions

    def _matches_pattern(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILENAME MATCHES ANY OF THE RULE'S REGEX PATTERNS.
        patterns = config.get("patterns", [])
        filename = Path(row.path).name
        return any(re.search(pattern, filename, re.IGNORECASE) for pattern in patterns)

    def _matches_date(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE'S MODIFICATION DATE FALLS WITHIN THE RULE'S DATE RANGE.
        if not row.modified_at:
            return False
        from datetime import datetime
        try:
            file_date = datetime.fromisoformat(row.modified_at)
        except ValueError:
            return False
        older_than_days = config.get("older_than_days")
        newer_than_days = config.get("newer_than_days")
        from datetime import timedelta
        now = datetime.now()
        if older_than_days is not None:
            if (now - file_date).days < older_than_days:
                return False
        if newer_than_days is not None:
            if (now - file_date).days > newer_than_days:
                return False
        return True

    def _matches_size(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE SIZE FALLS WITHIN THE RULE'S MIN/MAX SIZE RANGE.
        min_bytes = config.get("min_bytes", 0)
        max_bytes = config.get("max_bytes", float("inf"))
        return min_bytes <= row.size <= max_bytes

    def _matches_folder(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE'S FOLDER PATH MATCHES ANY OF THE RULE'S FOLDER PATTERNS.
        folder_patterns = config.get("folders", [])
        return any(
            re.search(pattern, row.folder_path, re.IGNORECASE)
            for pattern in folder_patterns
        )

    def _matches_status(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE'S STATUS MATCHES THE RULE'S REQUIRED STATUS VALUE.
        return row.status == config.get("status", "")

    def _apply_rule(self, row: ManifestRow, rule: dict) -> RuleMatch | None:
        # APPLIES A MATCHING RULE AND RETURNS A RuleMatch WITH THE PROPOSED DESTINATION PATH.
        destination_template = rule.get("destination_template", "")
        if not destination_template:
            return None
        proposed_path = self._render_destination(row, destination_template)
        action_type = rule.get("action_type", "move")
        return RuleMatch(
            original_path=row.path,
            proposed_path=proposed_path,
            action_type=action_type,
            rule_id=rule.get("id"),
            reason=f"Matched rule '{rule.get('name', 'unknown')}' ({rule.get('rule_type', 'unknown')})",
        )

    def _render_destination(self, row: ManifestRow, template: str) -> str:
        # RENDERS A DESTINATION PATH TEMPLATE BY SUBSTITUTING FILE METADATA PLACEHOLDERS.
        filename = Path(row.path).name
        stem = Path(row.path).stem
        extension = row.extension
        folder = row.folder_path
        result = template
        result = result.replace("{filename}", filename)
        result = result.replace("{stem}", stem)
        result = result.replace("{extension}", extension.lstrip("."))
        result = result.replace("{folder}", folder)
        result = result.replace("{root}", self.scan_root)
        result = result.replace("{date_year}", row.modified_at[:4] if row.modified_at else "unknown")
        return result
