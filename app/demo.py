"""Generate a realistic sample library for demos, tests and screenshots.

The generator is deterministic and uses only the libraries OpenCoeus already
depends on. It is intentionally *not* part of the normal application path: a
user should never have their own documents replaced by demo data.

Run it from the CLI::

    opencoeus demo ~/OpenCoeus-Demo
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def _write(path: Path, text: str) -> Path | None:
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_docx(path: Path, title: str, paragraphs: list[str]) -> Path | None:
    if path.exists():
        return None
    try:
        from docx import Document
    except ImportError:  # pragma: no cover - optional dependency
        return _write(path.with_suffix(".txt"), "\n\n".join([title, *paragraphs]))
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(title, level=1)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)
    return path


def _write_pdf(path: Path, title: str, lines: list[str]) -> Path | None:
    if path.exists():
        return None
    try:
        import fitz
    except ImportError:  # pragma: no cover - optional dependency
        return _write(path.with_suffix(".txt"), "\n".join([title, *lines]))
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), title, fontsize=18)
    y = 115
    for line in lines:
        page.insert_text((72, y), line, fontsize=10)
        y += 16
        if y > 780:
            page = document.new_page()
            y = 80
    document.save(path)
    document.close()
    return path


def _write_pptx(path: Path, title: str, bullets: list[str]) -> Path | None:
    if path.exists():
        return None
    try:
        from pptx import Presentation
    except ImportError:  # pragma: no cover - optional dependency
        return _write(path.with_suffix(".txt"), "\n".join([title, *bullets]))
    path.parent.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.text = bullets[0]
    for bullet in bullets[1:]:
        body.add_paragraph().text = bullet
    presentation.save(path)
    return path


def _write_xlsx(path: Path, rows: list[tuple[object, ...]]) -> Path | None:
    if path.exists():
        return None
    try:
        from openpyxl import Workbook
    except ImportError:  # pragma: no cover - optional dependency
        return _write(
            path.with_suffix(".csv"),
            "\n".join(",".join(str(cell) for cell in row) for row in rows),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget"
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


def _write_image(path: Path, colour: tuple[int, int, int]) -> Path | None:
    if path.exists():
        return None
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - optional dependency
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 420), colour)
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 610, 390), outline=(255, 255, 255), width=4)
    draw.text((60, 60), "Scanned document", fill=(255, 255, 255))
    draw.text((60, 100), "Receipt / invoice placeholder", fill=(230, 230, 230))
    image.save(path)
    return path


def create_sample_library(destination: Path) -> list[Path]:
    """Create a varied sample library beneath ``destination``.

    Existing files are left untouched, so the function is safe to run twice.
    Returns the paths that were created by this call.
    """

    root = Path(destination).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    def add(path: Path | None) -> None:
        if path is not None:
            created.append(path)

    add(
        _write_docx(
            root / "Downloads" / "assignment_final_v2.docx",
            "CS2018 Software Engineering Assignment",
            [
                "Module code: CS2018. Student ID: 20481922.",
                "Deadline: 12 May 2025. This coursework submission analyses requirements "
                "engineering for a local-first document assistant.",
                "Learning outcomes: apply elicitation techniques and evaluate a prototype.",
                "Marking rubric: requirements (30%), design (30%), evaluation (40%).",
            ],
        )
    )
    add(
        _write(
            root / "Downloads" / "lecture_notes_week03.md",
            "# Lecture Notes Week 3\n\n"
            "Learning outcomes: understand recursion and dynamic programming.\n\n"
            "This seminar covers the tutorial exercises and the reading list for week 3.\n",
        )
    )
    add(
        _write(
            root / "Desktop" / "research_paper_draft.txt",
            "A Hybrid Approach to Local Document Organisation\n\n"
            "Abstract\nThis paper presents a literature review and methodology for combining "
            "deterministic rules with semantic embeddings. Our research question asks whether "
            "a hybrid classifier outperforms either signal alone. Findings from the pilot "
            "experiment suggest a modest improvement. References and DOI links are included.\n",
        )
    )
    add(
        _write_pptx(
            root / "Desktop" / "seminar_presentation.pptx",
            "Final Year Project Progress",
            [
                "Agenda: problem, requirements, architecture, evaluation plan",
                "Learning outcomes and milestone review",
                "Next steps: user study and 300-document evaluation",
            ],
        )
    )
    add(
        _write(
            root / "Desktop" / "invoice_2024_0042.txt",
            "INVOICE\n\n"
            "Invoice number: INV-2024-0042\n"
            "Bill to: Northwind Systems Ltd\n"
            "Purchase order: PO-7781\n"
            "Subtotal: 1,250.00\nVAT: 250.00\nAmount due: 1,500.00\n"
            "Payment terms: 30 days. Please remit to the account below.\n",
        )
    )
    add(
        _write(
            root / "Desktop" / "receipt_shop.txt",
            "RECEIPT\n\n"
            "Cashier: 04\nOrder total: 18.40\nPaid: 20.00\nChange due: 1.60\n"
            "Transaction: 88213\nThank you for your purchase.\n",
        )
    )
    add(
        _write(
            root / "Documents" / "bank_statement_march.txt",
            "MONTHLY STATEMENT\n\n"
            "Account number: 12345678\nSort code: 40-11-22\nIBAN: GB00 TEST 0000 0000\n"
            "Opening balance: 2,300.00\nClosing balance: 1,980.25\n"
            "Transactions: credit salary, debit rent, debit utilities.\n",
        )
    )
    add(
        _write(
            root / "Documents" / "employment_contract.txt",
            "STATEMENT OF EMPLOYMENT\n\n"
            "This agreement is made between the parties: Northwind Systems Ltd and the employee.\n"
            "Termination requires four weeks notice. Confidentiality and governing law clauses apply.\n"
            "Signature: ______________  Witness: ______________\n",
        )
    )
    add(
        _write(
            root / "Documents" / "q3_business_report.md",
            "# Q3 Business Report\n\n"
            "Executive summary: revenue grew by 8%.\n\n"
            "Findings and recommendations for stakeholders. Action items are listed below.\n",
        )
    )
    add(
        _write(
            root / "Projects" / "api_reference.md",
            "# Local API Reference\n\n"
            "Installation and configuration guide.\n\n"
            "## Endpoints\n"
            "GET /health returns the service status.\n"
            "POST /search performs a hybrid search.\n"
            "Troubleshooting: check the command syntax and the schema version.\n",
        )
    )
    add(
        _write(
            root / "Personal" / "cv_2025.txt",
            "CURRICULUM VITAE\n\n"
            "Name: Alex Example\nDate of birth: 01/01/1999\n"
            "Personal statement: final-year computer science student.\n"
            "Experience with Python, SQL and user research.\n",
        )
    )
    add(
        _write_xlsx(
            root / "Finance" / "budget_forecast.xlsx",
            [
                ("Month", "Income", "Expenses", "Balance"),
                ("January", 2400, 1900, 500),
                ("February", 2400, 1750, 650),
                ("March", 2600, 2100, 500),
            ],
        )
    )
    add(
        _write(
            root / "Scans" / "scan_0041.txt",
            "Scanned letter\n\nDear resident,\nYour council tax statement for 2025 is enclosed.\n"
            "Payment is due by 31 March. Account number 99812.\n",
        )
    )
    add(_write_image(root / "Desktop" / "IMG_2043.jpg", (30, 60, 120)))
    add(_write_image(root / "Desktop" / "IMG_2044.jpg", (90, 40, 110)))

    original = root / "Desktop" / "invoice_2024_0042.txt"
    duplicate = root / "Downloads" / "invoice_2024_0042(1).txt"
    if original.is_file() and not duplicate.exists():
        duplicate.write_bytes(original.read_bytes())
        created.append(duplicate)

    add(
        _write(
            root / "Downloads" / "final final FINAL report (copy).txt",
            "Project report\n\n"
            "Executive summary and findings from the stakeholder survey.\n"
            "Recommendations and action items for the next quarter.\n",
        )
    )

    archive = root / "Downloads" / "old_archive.zip"
    if not archive.exists():
        archive.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        created.append(archive)

    add(
        _write_pdf(
            root / "University" / "course_handbook.pdf",
            "Course Handbook 2025",
            [
                "This handbook describes the module, assessment and lecture schedule.",
                "Please read the learning outcomes and the submission deadline carefully.",
                "Contact the module leader for seminar changes.",
                "Page 2",
            ],
        )
    )

    logger.info("Created %d sample files in %s", len(created), root)
    return created


__all__ = ["create_sample_library"]
