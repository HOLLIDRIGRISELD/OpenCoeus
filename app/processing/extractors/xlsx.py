"""XLSX extraction using openpyxl (read-only, data-only)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.archive import enforce_archive_limits
from app.processing.extractors.base import BaseExtractor

MAX_CELLS = 20_000


class XlsxExtractor(BaseExtractor):
    name = "xlsx"
    version = "1.1"
    formats = ("xlsx",)

    def extract(self, path: Path) -> ExtractionResult:
        warnings: list[str] = []
        enforce_archive_limits(path)
        try:
            workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        except Exception as exc:
            raise ExtractionError(f"Cannot open XLSX {path.name}: {exc}") from exc

        try:
            parts: list[str] = []
            cell_budget = MAX_CELLS
            chart_sheets = [sheet.title for sheet in workbook.chartsheets]
            for sheet in workbook.worksheets:
                sheet_name = sheet.title
                parts.append(f"[Sheet: {sheet_name}]")
                for row in sheet.iter_rows(values_only=True):
                    if cell_budget <= 0:
                        warnings.append("Workbook truncated after 20,000 cells.")
                        break
                    values = [str(value) for value in row if value not in (None, "")]
                    if values:
                        parts.append(" | ".join(values))
                        cell_budget -= len(values)
                if cell_budget <= 0:
                    break
            if chart_sheets:
                warnings.append(
                    f"Skipped {len(chart_sheets)} chart sheet(s) with no readable cell values."
                )

            text = "\n".join(parts).strip()
            if not text:
                warnings.append("The workbook contains no readable cell values.")

            properties = workbook.properties
            title = (properties.title or "").strip() or None
            return ExtractionResult(
                text=self._truncate(text, warnings),
                method=self.name,
                success=True,
                page_count=len(workbook.worksheets),
                title=title,
                author=(properties.creator or None),
                warnings=warnings,
                meta={"sheets": [sheet.title for sheet in workbook.worksheets], "chart_sheets": chart_sheets},
            )
        finally:
            workbook.close()
