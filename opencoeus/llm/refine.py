from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..extractors import _get_category, is_no_rename
from .engine import LLMEngine, clean_snippet
from .prompts import BATCH_SYSTEM_PROMPT, BATCH_USER_TEMPLATE

logger = logging.getLogger(__name__)

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def _sanitize_filename(name: str, ext: str) -> str:
    """Make an LLM/heuristic filename safe and extension-correct (lowercase server style)."""
    name = _INVALID_NAME_CHARS.sub("_", name)
    name = re.sub(r"[ _]{2,}", "_", name)
    name = name.strip(" ._-")
    if ext:
        if name.lower().endswith(ext.lower()):
            name = name[: -len(ext)]
        name = name.strip(" ._-")
    if not name:
        return ""
    return f"{name[:60].lower()}{ext}"


def _sanitize_subfolder(subfolder: str) -> str:
    """Normalize a subfolder into safe forward-slash parts under the base folder."""
    parts = []
    for part in subfolder.replace("\\", "/").split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(part)
    return "/".join(parts)


class RefineEngine:
    """Batch LLM refinement of rule destinations within their authoritative base folder.

    Every file keeps the base category folder chosen by the rules engine; the LLM
    only provides a context-based filename and a nested subfolder inside that base.
    Any LLM failure, empty result, or missing entry falls back to deterministic
    heuristic naming, so the pipeline never halts.
    """

    def __init__(self, llm_engine: LLMEngine, scan_root: str = "") -> None:
        self._llm = llm_engine
        self._scan_root = scan_root.rstrip("/").rstrip("\\")

    def refine_matches(self, pairs: list[tuple], locked_pairs: list[tuple] | None = None) -> None:
        """Refine ``(match, row)`` pairs in place, mutating the RuleMatch objects.

        ``locked_pairs`` items have already been co-located into a shared batch
        folder by the rules engine; only their filename is refined (the folder is
        never changed again).
        """
        items = [self._make_item(match, row) for match, row in pairs]
        items += [
            self._make_item(match, row, locked=True)
            for match, row in (locked_pairs or [])
        ]
        for batch in self._chunk(items):
            self._refine_batch(batch)

    def _make_item(self, match, row, locked: bool = False) -> dict:
        if is_no_rename(row.extension):
            return {"match": match, "row": row, "base": "", "keep_original": True, "locked": False}
        base = Path(match.proposed_path).parent
        base_rel = ""
        if self._scan_root:
            try:
                base_rel = base.relative_to(Path(self._scan_root)).as_posix()
            except ValueError:
                base_rel = ""
        if not base_rel:
            base_rel = base.name or ""
        return {"match": match, "row": row, "base": base_rel, "locked": locked}

    def _chunk(self, items: list[dict]) -> list[list[dict]]:
        budget_chars = self._token_budget()
        batches: list[list[dict]] = []
        current: list[dict] = []
        current_chars = 0
        for item in items:
            snippet = item["row"].text_snippet or ""
            size = min(len(snippet), 600) + 180
            if current and current_chars + size > budget_chars:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += size
            if len(current) >= self._llm.config.batch_size:
                batches.append(current)
                current = []
                current_chars = 0
        if current:
            batches.append(current)
        return batches

    def _token_budget(self) -> int:
        context = self._llm.config.context_length
        budget_tokens = max(400, context - 500)
        return budget_tokens * 3

    def _refine_batch(self, batch: list[dict]) -> None:
        if any(item.get("keep_original") for item in batch):
            for item in batch:
                if item.get("keep_original"):
                    self._keep_original(item)
            active = [item for item in batch if not item.get("keep_original")]
            if not active:
                return
            batch = active
        user_text = "".join(
            self._build_item_block(index, item) for index, item in enumerate(batch)
        )
        max_tokens = max(self._llm.config.max_tokens, 90 * len(batch))
        result = self._llm.complete(
            user_text,
            max_tokens=max_tokens,
            system_prompt=BATCH_SYSTEM_PROMPT,
        )
        if not result.success or not result.raw_output.strip():
            for item in batch:
                self._heuristic_fallback(item)
            return
        parsed = self._parse_batch_output(result.raw_output)
        for index, item in enumerate(batch):
            entry = parsed.get(index)
            if entry is not None:
                self._apply(item, entry[0], entry[1])
            else:
                self._heuristic_fallback(item)

    def _build_item_block(self, index: int, item: dict) -> str:
        row = item["row"]
        return BATCH_USER_TEMPLATE.format(
            index=index,
            base_folder=item["base"] or "",
            file_type=_get_category(row.extension),
            ext=row.extension.lstrip("."),
            doc_type=row.doc_type or "",
            topic=row.nlp_topic or "",
            author=row.nlp_author.replace("_", " ") if row.nlp_author else "",
            org=row.nlp_organization.replace("_", " ") if row.nlp_organization else "",
            date=row.nlp_date or "",
            keywords="",
            summary=row.nlp_summary or "",
            project=row.nlp_project.replace("_", " ") if row.nlp_project else "",
            location=row.nlp_location or "",
            camera=row.nlp_camera or "",
            artist=row.nlp_artist or "",
            album=row.nlp_album or "",
            text=clean_snippet(row.text_snippet, 600),
        )

    @staticmethod
    def _parse_batch_output(raw: str) -> dict[int, tuple[str, str]]:
        data = None
        array_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
            except (json.JSONDecodeError, ValueError):
                data = None
        if data is None:
            object_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if object_match:
                try:
                    data = json.loads(object_match.group(0))
                except (json.JSONDecodeError, ValueError):
                    data = None
        if data is None:
            return {}
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return {}
        parsed: dict[int, tuple[str, str]] = {}
        for position, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("index", position))
            except (TypeError, ValueError):
                continue
            if index < 0:
                continue
            filename = str(entry.get("filename", "") or "").strip()
            subfolder = str(entry.get("subfolder", "") or "").strip()
            parsed[index] = (filename, subfolder)
        return parsed

    def _apply(self, item: dict, filename: str, subfolder: str) -> None:
        match = item["match"]
        row = item["row"]
        new_name = _sanitize_filename(filename, row.extension)
        if not new_name:
            self._heuristic_fallback(item)
            return
        if item.get("locked"):
            sub = ""
        else:
            sub = _sanitize_subfolder(subfolder)
        sub_parts = sub.split("/") if sub else []
        base_first = item["base"].split("/")[0].lower() if item["base"] else ""
        if sub_parts and base_first and sub_parts[0].lower() == base_first:
            sub_parts = sub_parts[1:]
        base_path = Path(match.proposed_path).parent
        target_dir = base_path.joinpath(*sub_parts) if sub_parts else base_path
        target = target_dir / new_name
        new_path = str(target).replace("\\", "/")
        if new_path == match.proposed_path:
            return
        if match.action_type == "rename":
            match.action_type = "move+rename" if sub_parts else "rename"
        elif match.action_type == "move" and new_name != match.original_filename:
            match.action_type = "move+rename"
        match.proposed_path = new_path
        match.new_filename = new_name
        match.reason += " | Refined" + (f" into {sub}" if sub else "")

    @staticmethod
    def _keep_original(item: dict) -> None:
        match = item["match"]
        if Path(match.proposed_path).name != match.original_filename:
            match.proposed_path = str(
                Path(match.proposed_path).parent / match.original_filename
            ).replace("\\", "/")
            match.action_type = "move"
        match.new_filename = match.original_filename
        match.reason += " | Preserved server file name"

    def _heuristic_fallback(self, item: dict) -> None:
        match = item["match"]
        row = item["row"]
        ext = row.extension
        smart_name = row.smart_filename or ""
        if smart_name:
            filename = Path(smart_name).stem
        else:
            filename = (
                match.new_filename
                or match.original_filename
                or Path(match.original_path).stem
            )
        if item.get("locked"):
            self._apply(item, filename, "")
            return
        sub = row.smart_destination.replace("\\", "/").strip("/") if row.smart_destination else ""
        parts = [p for p in sub.split("/") if p] if sub else []
        base_first = item["base"].split("/")[0].lower() if item["base"] else ""
        if parts and base_first and parts[0].lower() == base_first:
            parts = parts[1:]
        self._apply(item, filename, "/".join(parts))
