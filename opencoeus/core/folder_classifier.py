from __future__ import annotations

import re

from ..config import CACHE_PATTERNS, DEPENDENCY_PATTERNS, VERSION_CONTROL_PATTERNS, VIRTUAL_ENVIRONMENT_PATTERNS
from .folder_tree import FolderNode


# WELL KNOWN DIRECTORY NAME PATTERNS FOR EACH CLASSIFICATION CATEGORY
# The virtual_environment/package_dependencies/version_control/source_code entries
# reference the shared pattern constants in config.py (single source of truth).
_PATTERNS = {
    "system": [
        # INTENTIONALLY CROSS-PLATFORM: CLASSIFIES KNOWN SYSTEM FOLDER NAMES REGARDLESS OF CURRENT OS.
        r"^windows$", r"^program files", r"^programdata$", r"^recovery$",
        r"^perflogs$", r"^msocache$", r"^\.Trashes$", r"^\.Spotlight",
        r"^proc$", r"^sys$", r"^dev$", r"^run$", r"^lost\+found$",
    ],
    "virtual_environment": VIRTUAL_ENVIRONMENT_PATTERNS + [
        r"^\.env$", r"^virtualenvs$", r"^site-packages$", r"^__pypackages__$",
    ],
    "package_dependencies": DEPENDENCY_PATTERNS + [
        r"^\.npm$", r"^bower_components$", r"^vendor$",
        r"^packages$", r"^\.pub-cache$", r"^Pods$",
        r"^\.bundle$", r"^Carthage$", r"^\.cabal-sandbox$",
    ],
    "version_control": VERSION_CONTROL_PATTERNS + [
        r"^\.svn$", r"^\.hg$", r"^\.bzr$",
        r"^_darcs$", r"^\.fslckout$", r"^\.CVS$",
    ],
    "game_library": [
        r"^Steam$", r"^Epic Games$", r"^GOG Galaxy$", r"^Origin$",
        r"^Battle\.net$", r"^Riot Games$", r"^Ubisoft$", r"^\.itch$",
        r"^Games$", r"^GameData$", r"^Saves$",
    ],
    "application": [
        r"^AppData$", r"^Application Support$", r"^\.config$",
        r"^\.local$", r"^Library$", r"^Downloads$", r"^Caches$",
        r"^Logs$", r"^CrashReports$", r"^Containers$",
    ],
    "source_code": [
        r"^src$", r"^lib$", r"^app$", r"^packages$",
        r"^\.vscode$", r"^\.idea$", r"^\.vs$", r"^\.eclipse$",
        r"^target$", r"^build$", r"^dist$", r"^out$",
    ] + CACHE_PATTERNS,
}


def classify_folder(
    node: FolderNode,
    compiled_patterns: dict[str, list[re.Pattern]] | None = None,
    custom_patterns: list[str] | None = None,
) -> tuple[str, str, str]:
    """Classify a folder and return (classification, recommended_action, reason).
    Checks the folder name against all well-known patterns."""
    folder_name = node.name
    if compiled_patterns is None:
        compiled_patterns = _compile_all_patterns(custom_patterns)
    for category, pattern_list in compiled_patterns.items():
        for pattern in pattern_list:
            if pattern.search(folder_name):
                action, reason = _action_for_category(category, node)
                return category, action, reason
    # PROTECTED FOLDERS THAT DID NOT MATCH A SPECIFIC PATTERN DEFAULT TO EXCLUDE
    if node.is_protected:
        return "system", "exclude", f"Folder '{folder_name}' is a protected system path."
    return "unknown", "ask_user", f"No specific rule matched for '{folder_name}'."


def _compile_all_patterns(
    custom_patterns: list[str] | None = None,
) -> dict[str, list[re.Pattern]]:
    """Compile all category patterns and any user-provided custom patterns into regex objects."""
    compiled = {}
    for category, raw_patterns in _PATTERNS.items():
        compiled[category] = [re.compile(p, re.IGNORECASE) for p in raw_patterns]
    if custom_patterns:
        compiled["custom"] = [re.compile(p, re.IGNORECASE) for p in custom_patterns]
    return compiled


def _action_for_category(category: str, node: FolderNode) -> tuple[str, str]:
    """Determine the recommended action and explanation for each classification category."""
    if category == "system":
        return "exclude", f"System folder '{node.name}' should not be modified."
    if category == "virtual_environment":
        return "exclude", f"Virtual environment '{node.name}' contains installed packages, not user data."
    if category == "package_dependencies":
        return "exclude", f"Dependency folder '{node.name}' is auto generated and should not be organized."
    if category == "version_control":
        return "exclude", f"Version control folder '{node.name}' manages project history and must stay in place."
    if category == "game_library":
        return "exclude", f"Game library folder '{node.name}' is managed by game software and should not be moved."
    if category == "application":
        return "exclude", f"Application support folder '{node.name}' is used by installed software."
    if category == "source_code":
        return "ask_user", f"Source code folder '{node.name}' may contain project files, review before organizing."
    if category == "custom":
        return "ask_user", f"Custom rule matched folder '{node.name}', review before organizing."
    return "ask_user", f"Unknown folder type for '{node.name}'."


def classify_tree(
    root: FolderNode,
    custom_patterns: list[str] | None = None,
) -> list[dict]:
    """Walk the entire tree and classify every folder, returning a list of classification dicts."""
    compiled = _compile_all_patterns(custom_patterns)
    classifications = []
    _classify_recursive(root, compiled, classifications)
    return classifications


def _classify_recursive(
    node: FolderNode,
    compiled_patterns: dict[str, list[re.Pattern]],
    accumulator: list[dict],
) -> None:
    """Classify the current node and recursively process all children."""
    classification, action, reason = classify_folder(node, compiled_patterns)
    node.classification = classification
    node.recommended_action = action
    accumulator.append({
        "folder_path": node.path.as_posix(),
        "classification": classification,
        "recommended_action": action,
        "reason": reason,
        "user_override": None,
    })
    for child in node.children:
        _classify_recursive(child, compiled_patterns, accumulator)
