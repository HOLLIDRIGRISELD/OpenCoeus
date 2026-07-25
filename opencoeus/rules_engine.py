from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .engine import ManifestRow
from .profiles import ProfileConfig


# DEFAULT RULES

DEFAULT_RULES = [
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
]


@dataclass
class RuleMatch:
    # REPRESENTS A SINGLE RULE MATCH RESULT WITH THE PROPOSED ACTION DETAILS
    original_path: str
    proposed_path: str
    action_type: str
    rule_id: int | None = None
    reason: str = ""


class RulesEngine:
    # DETERMINISTIC RULES ENGINE THAT PROPOSES FILE ACTIONS WITHOUT AI
    # APPLIES EXTENSION, PATTERN, DATE, SIZE, AND FOLDER BASED RULES IN PRIORITY ORDER

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
            # PRE COMPILE REGEX PATTERNS AND EXTENSION SETS FOR PERFORMANCE
            config = prepared["_parsed_config"]
            if "patterns" in config:
                prepared["_compiled_patterns"] = [
                    re.compile(p, re.IGNORECASE) for p in config["patterns"]
                ]
            if "extensions" in config:
                prepared["_compiled_extensions"] = {
                    ext.lower() for ext in config["extensions"]
                }
            if "folders" in config:
                prepared["_compiled_folders"] = [
                    re.compile(p, re.IGNORECASE) for p in config["folders"]
                ]
            prepared_rules.append(prepared)
        sorted_rules = sorted(prepared_rules, key=lambda r: r.get("priority", 0))
        profile_excluded = set(self.profile.excluded_folders) if self.profile else set()
        profile_included = self.profile.included_folders if self.profile else []
        matches: list[RuleMatch] = []
        for row in manifest_rows:
            if row.status in {"unreadable", "protected"}:
                continue
            if profile_excluded and any(
                row.folder_path == ex or row.folder_path.startswith(ex + os.sep)
                for ex in profile_excluded
            ):
                continue
            if profile_included and not any(
                row.folder_path == inc or row.folder_path.startswith(inc + os.sep)
                for inc in profile_included
            ):
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

    def _matches_pattern(self, row: ManifestRow, rule: dict) -> bool:
        # CHECKS WHETHER THE FILENAME MATCHES ANY OF THE RULE REGEX PATTERNS
        compiled = rule.get("_compiled_patterns")
        filename = Path(row.path).name
        if compiled is not None:
            return any(p.search(filename) for p in compiled)
        config = rule.get("_parsed_config", {})
        patterns = config.get("patterns", [])
        return any(re.search(pattern, filename, re.IGNORECASE) for pattern in patterns)

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
        # CHECKS WHETHER THE FILE FOLDER PATH MATCHES ANY OF THE RULE FOLDER PATTERNS
        compiled = rule.get("_compiled_folders")
        if compiled is not None:
            return any(p.search(row.folder_path) for p in compiled)
        config = rule.get("_parsed_config", {})
        folder_patterns = config.get("folders", [])
        return any(
            re.search(pattern, row.folder_path, re.IGNORECASE)
            for pattern in folder_patterns
        )

    def _matches_status(self, row: ManifestRow, config: dict) -> bool:
        # CHECKS WHETHER THE FILE STATUS MATCHES THE RULE REQUIRED STATUS VALUE
        return row.status == config.get("status", "")

    def _apply_rule(self, row: ManifestRow, rule: dict) -> RuleMatch | None:
        # APPLIES A MATCHING RULE AND RETURNS A RULE MATCH WITH THE PROPOSED DESTINATION PATH
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
        # RENDERS A DESTINATION PATH TEMPLATE BY SUBSTITUTING FILE METADATA PLACEHOLDERS
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
        date_year = row.modified_at[:4] if row.modified_at and len(row.modified_at) >= 4 else "unknown"
        result = result.replace("{date_year}", date_year)
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
