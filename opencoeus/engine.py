from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import ScanSettings
from .database import AuditStore
from .documents import extract_text, suggest_title
from .folder_classifier import classify_tree
from .folder_tree import FolderNode, build_folder_tree, flatten_tree
from .hashing import sha256_file
from .safety import is_protected
from .scanner import FileRecord, iter_files


@dataclass
class ManifestRow:
    path: str
    size: int
    sha256: str
    status: str
    duplicate_of: str = ""
    suggested_title: str = ""
    # STAGE 2: EXTENDED METADATA FOR RULE-BASED ORGANIZATION.
    relative_path: str = ""
    extension: str = ""
    modified_at: str = ""
    folder_path: str = ""


@dataclass
class ScanResult:
    rows: list[ManifestRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # STAGE 2: FOLDER TREE AND CLASSIFICATION DATA FOR THE UI.
    folder_tree_flat: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return sum(row.status == "duplicate" for row in self.rows)


class ScanEngine:
    def __init__(self, settings: ScanSettings, store: AuditStore | None = None) -> None:
        self.settings, self.store = settings, store or AuditStore()

    def run(self, progress_callback: Callable[[str], None] | None = None) -> ScanResult:
        # BACKWARD-COMPATIBLE SINGLE-PHASE SCAN FOR STAGE 1 CLI.
        scan_result = ScanResult()
        self._scan_files(scan_result, progress_callback)
        return scan_result

    def run_phase_one(self, progress_callback: Callable[[str], None] | None = None,
                      custom_patterns: list[str] | None = None) -> ScanResult:
        # PHASE 1: DISCOVERS THE FOLDER TREE AND CLASSIFIES EVERY FOLDER.
        scan_result = ScanResult()
        folder_tree_root = build_folder_tree(
            self.settings.root,
            self.settings.protected_patterns,
            progress_callback=progress_callback,
        )
        scan_result.classifications = classify_tree(folder_tree_root, custom_patterns)
        scan_result.folder_tree_flat = flatten_tree(folder_tree_root)
        self.store.save_classifications(1, scan_result.classifications)
        return scan_result

    def run_phase_two(self, excluded_folders: set[str] | None = None,
                      progress_callback: Callable[[str], None] | None = None) -> ScanResult:
        # PHASE 2: SCANS FILES WITHIN NON-EXCLUDED FOLDERS AND DETECTS DUPLICATES.
        scan_result = ScanResult()
        self._scan_files(scan_result, progress_callback, excluded_folders)
        return scan_result

    def _scan_files(self, scan_result: ScanResult, progress_callback: Callable[[str], None] | None = None,
                    excluded_folders: set[str] | None = None) -> None:
        # SHARED FILE SCANNING LOGIC USED BY BOTH run() AND run_phase_two().
        discovered_files: list[FileRecord] = list(iter_files(self.settings.root, scan_result.errors.append))
        if excluded_folders:
            discovered_files = [f for f in discovered_files if not self._is_in_excluded_folder(f, excluded_folders)]
        files_grouped_by_size: dict[int, list[FileRecord]] = defaultdict(list)
        for file_record in discovered_files:
            files_grouped_by_size[file_record.size].append(file_record)
        first_file_by_hash: dict[str, Path] = {}
        for file_number, file_record in enumerate(discovered_files, 1):
            if progress_callback:
                progress_callback(f"{file_number}/{len(discovered_files)}  {file_record.path}")
            relative_file_path = file_record.path.relative_to(self.settings.root)
            is_protected_file = is_protected(relative_file_path, self.settings.protected_patterns)
            file_hash = ""
            file_status, original_file_path = ("protected", "") if is_protected_file else ("unique", "")
            if not is_protected_file and len(files_grouped_by_size[file_record.size]) > 1:
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
            if self.settings.extract_documents and file_status in {"unique", "protected"} and file_record.path.suffix.lower() in {".pdf", ".docx"}:
                suggested_title = suggest_title(extract_text(file_record.path), file_record.path.stem)
                suggested_title = self.store.reserve_title(suggested_title, str(file_record.path))
            self.store.record_file(str(file_record.path), file_record.size, file_hash or None, file_status)
            scan_result.rows.append(ManifestRow(
                path=str(file_record.path),
                size=file_record.size,
                sha256=file_hash,
                status=file_status,
                duplicate_of=original_file_path,
                suggested_title=suggested_title,
                relative_path=file_record.relative_path,
                extension=file_record.extension,
                modified_at=file_record.modified_at.isoformat() if file_record.modified_at else "",
                folder_path=file_record.folder_path,
            ))

    def _is_in_excluded_folder(self, file_record: FileRecord, excluded_folders: set[str]) -> bool:
        # CHECKS WHETHER A FILE'S FOLDER PATH MATCHES ANY EXCLUDED FOLDER.
        for excluded_folder in excluded_folders:
            if file_record.folder_path.startswith(excluded_folder):
                return True
        return False


def write_manifest(scan_result: ScanResult, destination_path: Path) -> None:
    # WRITES REVIEWABLE RESULTS TO CSV WITHOUT CHANGING ANY SCANNED FILE.
    with destination_path.open("w", newline="", encoding="utf-8-sig") as csv_output_file:
        csv_writer = csv.DictWriter(csv_output_file, fieldnames=[
            "path", "size", "sha256", "status", "duplicate_of", "suggested_title",
            "relative_path", "extension", "modified_at", "folder_path",
        ])
        csv_writer.writeheader()
        csv_writer.writerows(manifest_row.__dict__ for manifest_row in scan_result.rows)
