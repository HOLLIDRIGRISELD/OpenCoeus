from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ManifestRow:
    path: str
    size: int
    sha256: str
    status: str
    duplicate_of: str = ""
    suggested_title: str = ""
    relative_path: str = ""
    extension: str = ""
    modified_at: str = ""
    folder_path: str = ""
    size_kb: float = 0.0
    size_mb: float = 0.0
    date_iso: str = ""
    date_month: str = ""
    date_day: str = ""
    date_full: str = ""
    doc_type: str = ""
    nlp_topic: str = ""
    nlp_author: str = ""
    nlp_organization: str = ""
    nlp_project: str = ""
    nlp_summary: str = ""
    nlp_confidence: float = 0.0
    nlp_date: str = ""
    nlp_location: str = ""
    nlp_camera: str = ""
    nlp_artist: str = ""
    nlp_album: str = ""
    smart_filename: str = ""
    smart_destination: str = ""
    text_snippet: str = ""


@dataclass
class ScanResult:
    rows: list[ManifestRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    folder_tree_flat: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return sum(row.status == "duplicate" for row in self.rows)


def write_manifest(scan_result: ScanResult, destination_path: Path) -> None:
    with destination_path.open("w", newline="", encoding="utf-8-sig") as csv_output_file:
        csv_writer = csv.DictWriter(csv_output_file, fieldnames=[
            "path", "size", "sha256", "status", "duplicate_of", "suggested_title",
            "relative_path", "extension", "modified_at", "folder_path",
            "size_kb", "size_mb", "date_iso", "date_month", "date_day", "date_full",
            "doc_type",
            "nlp_topic", "nlp_author", "nlp_organization", "nlp_project",
            "nlp_summary", "nlp_confidence", "nlp_date", "nlp_location",
            "nlp_camera", "nlp_artist", "nlp_album",
            "smart_filename", "smart_destination", "text_snippet",
        ])
        csv_writer.writeheader()
        csv_writer.writerows(manifest_row.__dict__ for manifest_row in scan_result.rows)
