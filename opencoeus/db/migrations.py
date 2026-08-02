from __future__ import annotations

import re

_DATE_TOKEN_SUBSTITUTIONS = [
    ("{date_iso}_", ""),
    ("{date_year}_", ""),
    ("{date_month}_", ""),
    ("{date_day}_", ""),
    ("{date_iso}", ""),
    ("{date_year}", ""),
    ("{date_month}", ""),
    ("{date_day}", ""),
]


def _strip_date_tokens(template: str) -> str:
    """Remove date placeholder tokens from a rule template, collapsing empty paths."""
    result = template
    for token, replacement in _DATE_TOKEN_SUBSTITUTIONS:
        result = result.replace(token, replacement)
    result = re.sub(r"/{2,}", "/", result)
    return result.strip(" _-")


def strip_dates_from_rule_templates(store) -> dict:
    """Idempotently strip date tokens from stored rule templates across all profiles.

    Also disables archive rules (no Archive folder) and any rename rule that becomes
    a no-op once its date prefix is removed (e.g. ``{date_iso}_{filename}``).
    Returns a summary of how many rules were changed/disabled.
    """
    rules_changed = 0
    rules_disabled = 0
    for profile in store.list_profiles():
        for rule in store.get_rules(profile.id):
            rename = rule.rename_template or ""
            destination = rule.destination_template or ""
            new_rename = _strip_date_tokens(rename)
            new_destination = _strip_date_tokens(destination)
            is_archive = "archive" in (rule.name or "").lower() or "old file" in (rule.name or "").lower()
            is_no_op = (
                rule.action_type == "rename"
                and new_rename.replace(".{extension}", "") in ("{filename}", "{stem}")
            )
            disable = is_archive or is_no_op
            if not (new_rename != rename or new_destination != destination or disable):
                continue
            kwargs = {
                "rename_template": new_rename,
                "destination_template": new_destination,
            }
            if disable and rule.enabled:
                kwargs["enabled"] = False
                rules_disabled += 1
            store.update_rule(rule.id, **kwargs)
            rules_changed += 1
    return {"rules_changed": rules_changed, "rules_disabled": rules_disabled}
