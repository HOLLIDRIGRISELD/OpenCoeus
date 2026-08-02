from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

from ..config import ScanSettings
from ..core.file_scan import FileRecord, iter_files
from ..core.folder_classifier import classify_tree
from ..core.folder_tree import build_folder_tree, flatten_tree
from ..core.hashing import sha256_file
from ..core.safety import is_protected
from ..db import AuditStore
from ..extractors import extract_all, _get_category, extract_text, suggest_title, detect_document_type, extract_metadata
from ..llm.engine import clean_snippet
from ..nlp import NLPEngine
from .manifest import ManifestRow, ScanResult

logger = logging.getLogger(__name__)

_NLP_SKIP_CATEGORIES = frozenset({"installer", "system", "temp"})


class ScanEngine:

    def __init__(self, settings: ScanSettings, store: AuditStore | None = None) -> None:
        self.settings, self.store = settings, store or AuditStore()
        profile = getattr(settings, 'profile', None)
        nlp_threshold = profile.nlp_confidence_threshold if profile else 0.0
        self.nlp_engine = NLPEngine(confidence_threshold=nlp_threshold)

    def run(self, progress_callback: Callable[[str], None] | None = None) -> ScanResult:
        scan_result = ScanResult()
        self._scan_files(scan_result, progress_callback)
        return scan_result

    def run_phase_one(self, progress_callback: Callable[[str], None] | None = None,
                      custom_patterns: list[str] | None = None,
                      profile_id: int = 1) -> ScanResult:
        scan_result = ScanResult()
        logger.info("Phase 1: scanning %s", self.settings.root)
        merged_patterns = self.settings.protected_patterns + (custom_patterns or [])
        folder_tree_root = build_folder_tree(
            self.settings.root,
            merged_patterns,
            progress_callback=progress_callback,
        )
        scan_result.classifications = classify_tree(folder_tree_root, custom_patterns)
        scan_result.folder_tree_flat = flatten_tree(folder_tree_root)
        self.store.save_classifications(profile_id, scan_result.classifications)
        logger.info("Phase 1 complete: %d folders classified", len(scan_result.classifications))
        return scan_result

    def run_phase_two(self, excluded_folders: set[str] | None = None,
                      progress_callback: Callable[[str], None] | None = None,
                      included_folders: list[str] | None = None,
                      extract_documents: bool | None = None) -> ScanResult:
        scan_result = ScanResult()
        logger.info("Phase 2: scanning files in %s", self.settings.root)
        effective_extract = extract_documents if extract_documents is not None else self.settings.extract_documents
        self._scan_files(scan_result, progress_callback, excluded_folders, included_folders, effective_extract)
        logger.info("Phase 2 complete: %d files, %d duplicates", len(scan_result.rows), scan_result.duplicate_count)
        return scan_result

    def _scan_files(self, scan_result: ScanResult, progress_callback: Callable[[str], None] | None = None,
                    excluded_folders: set[str] | None = None,
                    included_folders: list[str] | None = None,
                    extract_documents: bool | None = None) -> None:
        discovered_files: list[FileRecord] = list(iter_files(self.settings.root, scan_result.errors.append))
        if excluded_folders:
            discovered_files = [f for f in discovered_files if not self._is_in_excluded_folder(f, excluded_folders)]
        if included_folders:
            discovered_files = [f for f in discovered_files if self._is_in_included_folder(f, included_folders)]
        use_extraction = extract_documents if extract_documents is not None else self.settings.extract_documents
        files_grouped_by_size: dict[int, list[FileRecord]] = defaultdict(list)
        for file_record in discovered_files:
            files_grouped_by_size[file_record.size].append(file_record)
        first_file_by_hash: dict[str, Path] = {}
        batch_records: list[tuple] = []
        total_files = len(discovered_files)
        last_progress_at = [0.0]
        if progress_callback and total_files:
            progress_callback(f"Scanning {total_files} files...")
        for file_number, file_record in enumerate(discovered_files, 1):
            if progress_callback:
                now = time.monotonic()
                if now - last_progress_at[0] >= 0.5 or file_number == total_files:
                    last_progress_at[0] = now
                    progress_callback(f"{file_number}/{total_files}  {file_record.path}")
            try:
                relative_file_path = file_record.path.relative_to(self.settings.root)
            except ValueError:
                relative_file_path = file_record.path
            is_protected_file = is_protected(relative_file_path, self.settings.protected_patterns)
            file_hash = ""
            file_status, original_file_path = ("protected", "") if is_protected_file else ("unique", "")
            if not is_protected_file and file_record.size > 0 and len(files_grouped_by_size[file_record.size]) > 1:
                try:
                    file_hash = sha256_file(file_record.path, self.settings.chunk_size)
                    if file_hash in first_file_by_hash:
                        file_status, original_file_path = "duplicate", str(first_file_by_hash[file_hash])
                    else:
                        first_file_by_hash[file_hash] = file_record.path
                except OSError as file_error:
                    file_status = "unreadable"
                    scan_result.errors.append(f"Cannot hash {file_record.path}: {file_error}")
            suggested_title = ""
            doc_type = ""
            nlp_topic = nlp_author = nlp_organization = nlp_project = ""
            nlp_summary = nlp_date = nlp_location = nlp_camera = nlp_artist = nlp_album = ""
            smart_filename = smart_destination = ""
            nlp_confidence = 0.0
            text_snippet = ""
            category = ""
            if use_extraction and file_status in {"unique", "protected"}:
                ext = file_record.path.suffix.lower()
                category = _get_category(ext)
                if ext in {".pdf", ".docx", ".txt", ".md"}:
                    extracted_text = extract_text(file_record.path)
                    suggested_title = suggest_title(extracted_text, file_record.path.stem)
                    suggested_title = self.store.reserve_title(suggested_title, str(file_record.path))
                    metadata = extract_metadata(file_record.path) if ext in {".pdf", ".docx"} else {}
                    doc_type = detect_document_type(extracted_text, metadata, suggested_title)
                if category not in _NLP_SKIP_CATEGORIES:
                    try:
                        signals = extract_all(file_record.path)
                        text_snippet = clean_snippet(signals.text)
                        nlp_result = self.nlp_engine.analyze(file_record.path, signals, file_record.path.stem)
                        nlp_topic = nlp_result.topic
                        nlp_author = nlp_result.author
                        nlp_organization = nlp_result.organization
                        nlp_project = nlp_result.project
                        nlp_summary = nlp_result.summary
                        nlp_confidence = nlp_result.confidence
                        nlp_date = nlp_result.date
                        nlp_location = nlp_result.location
                        nlp_camera = nlp_result.camera_model
                        nlp_artist = nlp_result.artist
                        nlp_album = nlp_result.album
                        smart_filename = nlp_result.smart_filename
                        smart_destination = nlp_result.smart_destination
                    except Exception as nlp_error:
                        logger.debug("NLP analysis failed for %s: %s", file_record.path, nlp_error)
            batch_records.append((
                str(file_record.path), file_record.size, file_hash or None, file_status,
                file_record.relative_path, file_record.extension,
                file_record.modified_at, file_record.folder_path,
            ))
            scan_result.rows.append(ManifestRow(
                path=str(file_record.path),
                size=file_record.size,
                sha256=file_hash,
                status=file_status,
                duplicate_of=original_file_path,
                suggested_title=suggested_title,
                doc_type=doc_type,
                relative_path=file_record.relative_path,
                extension=file_record.extension,
                modified_at=file_record.modified_at.isoformat() if file_record.modified_at else "",
                folder_path=file_record.folder_path,
                size_kb=round(file_record.size / 1024, 1) if file_record.size > 0 else 0.0,
                size_mb=round(file_record.size / (1024 * 1024), 2) if file_record.size > 0 else 0.0,
                date_iso=file_record.modified_at.strftime("%Y-%m-%d") if file_record.modified_at else "",
                date_month=file_record.modified_at.strftime("%m") if file_record.modified_at else "",
                date_day=file_record.modified_at.strftime("%d") if file_record.modified_at else "",
                date_full=file_record.modified_at.strftime("%Y-%m-%d %H:%M") if file_record.modified_at else "",
                nlp_topic=nlp_topic,
                nlp_author=nlp_author,
                nlp_organization=nlp_organization,
                nlp_project=nlp_project,
                nlp_summary=nlp_summary,
                nlp_confidence=nlp_confidence,
                nlp_date=nlp_date,
                nlp_location=nlp_location,
                nlp_camera=nlp_camera,
                nlp_artist=nlp_artist,
                nlp_album=nlp_album,
                smart_filename=smart_filename,
                smart_destination=smart_destination,
                text_snippet=text_snippet,
            ))
        self.store.record_files_batch(batch_records)

    def _is_in_excluded_folder(self, file_record: FileRecord, excluded_folders: set[str]) -> bool:
        normalized = file_record.folder_path.replace("\\", "/")
        for excluded_folder in excluded_folders:
            excluded_normalized = excluded_folder.replace("\\", "/").rstrip("/")
            if normalized == excluded_normalized or normalized.startswith(excluded_normalized + "/"):
                return True
        return False

    def _is_in_included_folder(self, file_record: FileRecord, included_folders: list[str]) -> bool:
        normalized = file_record.folder_path.replace("\\", "/")
        for included_folder in included_folders:
            included_normalized = included_folder.replace("\\", "/").rstrip("/")
            if normalized == included_normalized or normalized.startswith(included_normalized + "/"):
                return True
        return False
