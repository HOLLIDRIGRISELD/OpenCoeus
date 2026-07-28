from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import ScanSettings
from .database import AuditStore
from .documents import extract_text, suggest_title, detect_document_type, extract_metadata
from .folder_classifier import classify_tree
from .folder_tree import build_folder_tree, flatten_tree
from .hashing import sha256_file
from .safety import is_protected
from .scanner import FileRecord, iter_files

logger = logging.getLogger(__name__)


@dataclass
class ManifestRow:
    path: str
    size: int
    sha256: str
    status: str
    duplicate_of: str = ""
    suggested_title: str = ""
    # STAGE 2: EXTENDED METADATA FOR RULE-BASED ORGANIZATION
    relative_path: str = ""
    extension: str = ""
    modified_at: str = ""
    folder_path: str = ""
    # STAGE 4: COMPUTED METADATA FOR TEMPLATE VARIABLE RENDERING
    size_kb: float = 0.0
    size_mb: float = 0.0
    date_iso: str = ""
    date_month: str = ""
    date_day: str = ""
    date_full: str = ""
    # STAGE 5: CONTENT-AWARE DOCUMENT TYPE
    doc_type: str = ""


@dataclass
class ScanResult:
    rows: list[ManifestRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # STAGE 2: FOLDER TREE AND CLASSIFICATION DATA FOR THE UI
    folder_tree_flat: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return sum(row.status == "duplicate" for row in self.rows)


class ScanEngine:

    def __init__(self, settings: ScanSettings, store: AuditStore | None = None) -> None:
        self.settings, self.store = settings, store or AuditStore()

    def run(self, progress_callback: Callable[[str], None] | None = None) -> ScanResult:
        # BACKWARD-COMPATIBLE SINGLE-PHASE SCAN FOR STAGE 1 CLI
        scan_result = ScanResult()
        self._scan_files(scan_result, progress_callback)
        return scan_result

    def run_phase_one(self, progress_callback: Callable[[str], None] | None = None,
                      custom_patterns: list[str] | None = None,
                      profile_id: int = 1) -> ScanResult:
        # PHASE 1: DISCOVERS THE FOLDER TREE AND CLASSIFIES EVERY FOLDER
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
        # PHASE 2: SCANS FILES WITHIN NON-EXCLUDED FOLDERS AND DETECTS DUPLICATES
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
        # SHARED FILE SCANNING LOGIC USED BY BOTH run() AND run_phase_two()
        discovered_files: list[FileRecord] = list(iter_files(self.settings.root, scan_result.errors.append))
        # FILTER IN-PLACE TO AVOID CREATING EXTRA LIST COPIES
        if excluded_folders:
            discovered_files = [f for f in discovered_files if not self._is_in_excluded_folder(f, excluded_folders)]
        if included_folders:
            discovered_files = [f for f in discovered_files if self._is_in_included_folder(f, included_folders)]
        use_extraction = extract_documents if extract_documents is not None else self.settings.extract_documents
        # GROUP BY SIZE IN SINGLE PASS FOR DUPLICATE DETECTION
        files_grouped_by_size: dict[int, list[FileRecord]] = defaultdict(list)
        for file_record in discovered_files:
            files_grouped_by_size[file_record.size].append(file_record)
        first_file_by_hash: dict[str, Path] = {}
        batch_records: list[tuple] = []
        total_files = len(discovered_files)
        for file_number, file_record in enumerate(discovered_files, 1):
            if progress_callback and (file_number % 50 == 0 or file_number == total_files):
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
            if use_extraction and file_status in {"unique", "protected"} and file_record.path.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}:
                extracted_text = extract_text(file_record.path)
                suggested_title = suggest_title(extracted_text, file_record.path.stem)
                suggested_title = self.store.reserve_title(suggested_title, str(file_record.path))
                metadata = extract_metadata(file_record.path) if file_record.path.suffix.lower() in {".pdf", ".docx"} else {}
                doc_type = detect_document_type(extracted_text, metadata, suggested_title)
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
            ))
        self.store.record_files_batch(batch_records)

    def _is_in_excluded_folder(self, file_record: FileRecord, excluded_folders: set[str]) -> bool:
        # CHECKS WHETHER A FILE FOLDER PATH MATCHES ANY EXCLUDED FOLDER
        normalized = file_record.folder_path.replace("\\", "/")
        for excluded_folder in excluded_folders:
            excluded_normalized = excluded_folder.replace("\\", "/").rstrip("/")
            if normalized == excluded_normalized or normalized.startswith(excluded_normalized + "/"):
                return True
        return False

    def _is_in_included_folder(self, file_record: FileRecord, included_folders: list[str]) -> bool:
        # CHECKS WHETHER A FILE FOLDER PATH MATCHES ANY INCLUDED FOLDER
        normalized = file_record.folder_path.replace("\\", "/")
        for included_folder in included_folders:
            included_normalized = included_folder.replace("\\", "/").rstrip("/")
            if normalized == included_normalized or normalized.startswith(included_normalized + "/"):
                return True
        return False


def write_manifest(scan_result: ScanResult, destination_path: Path) -> None:
    # WRITES REVIEWABLE RESULTS TO CSV WITHOUT CHANGING ANY SCANNED FILE
    with destination_path.open("w", newline="", encoding="utf-8-sig") as csv_output_file:
        csv_writer = csv.DictWriter(csv_output_file, fieldnames=[
            "path", "size", "sha256", "status", "duplicate_of", "suggested_title",
            "relative_path", "extension", "modified_at", "folder_path",
            "size_kb", "size_mb", "date_iso", "date_month", "date_day", "date_full",
            "doc_type",
        ])
        csv_writer.writeheader()
        csv_writer.writerows(manifest_row.__dict__ for manifest_row in scan_result.rows)
