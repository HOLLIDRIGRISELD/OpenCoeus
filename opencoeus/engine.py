from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import ScanSettings
from .database import AuditStore
from .documents import extract_text, suggest_title
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


@dataclass
class ScanResult:
    rows: list[ManifestRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return sum(row.status == "duplicate" for row in self.rows)


class ScanEngine:
    def __init__(self, settings: ScanSettings, store: AuditStore | None = None) -> None:
        self.settings, self.store = settings, store or AuditStore()

    def run(self, progress_callback: Callable[[str], None] | None = None) -> ScanResult:
        scan_result = ScanResult()
        # COLLECTS FILE METADATA BEFORE HASHING SO UNIQUE FILE SIZES ARE NOT READ TWICE.
        discovered_files: list[FileRecord] = list(iter_files(self.settings.root, scan_result.errors.append))
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
                    # HASHES ONLY SAME-SIZE FILES, BECAUSE DIFFERENT SIZES CANNOT BE DUPLICATES.
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
            scan_result.rows.append(
                ManifestRow(str(file_record.path), file_record.size, file_hash, file_status, original_file_path, suggested_title)
            )
        return scan_result


def write_manifest(scan_result: ScanResult, destination_path: Path) -> None:
    # WRITES REVIEWABLE RESULTS TO CSV WITHOUT CHANGING ANY SCANNED FILE.
    with destination_path.open("w", newline="", encoding="utf-8-sig") as csv_output_file:
        csv_writer = csv.DictWriter(csv_output_file, fieldnames=["path", "size", "sha256", "status", "duplicate_of", "suggested_title"])
        csv_writer.writeheader()
        csv_writer.writerows(manifest_row.__dict__ for manifest_row in scan_result.rows)
