"""Scanner page: discover files and run the analysis pipeline."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
)

from app.ui.base import BasePage
from app.ui.widgets import (
    Card,
    FlowLayout,
    LineEdit,
    hint_label,
    muted_label,
    scrollable_page,
)


class ScannerPage(BasePage):
    library_changed = Signal()
    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._scan_task = None
        self._analyse_task = None
        self._build()

    def _build(self) -> None:
        layout = scrollable_page(self)

        scan_card = Card("1 · Choose a folder", subtitle="scanning never modifies your files")
        path_row = QHBoxLayout()
        self.path_edit = LineEdit()
        self.path_edit.setPlaceholderText("/home/you/Documents or C:\\Users\\you\\Documents")
        self.path_edit.returnPressed.connect(self.start_scan)
        path_row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        scan_card.add_layout(path_row)

        options = FlowLayout()
        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        self.hash_check = QCheckBox("Compute SHA-256 hashes")
        self.hash_check.setChecked(True)
        self.unsupported_check = QCheckBox("Register unsupported formats")
        options.addWidget(self.recursive_check)
        options.addWidget(self.hash_check)
        options.addWidget(self.unsupported_check)
        scan_card.add_layout(options)
        scan_card.add(hint_label("SHA-256 hashes are needed for duplicate detection."))

        buttons = QHBoxLayout()
        self.scan_button = QPushButton("Start scan")
        self.scan_button.setProperty("primary", True)
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_cancel = QPushButton("Cancel")
        self.scan_cancel.setEnabled(False)
        self.scan_cancel.clicked.connect(lambda: self._scan_task and self._scan_task.cancel())
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.scan_cancel)
        buttons.addStretch(1)
        scan_card.add_layout(buttons)

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setFixedHeight(8)
        scan_card.add(self.scan_progress)
        self.scan_status = muted_label("Idle. The root of the most recent scan is used for folder recommendations.")
        scan_card.add(self.scan_status)
        layout.addWidget(scan_card)

        analyse_card = Card("2 · Analyse the library", subtitle="extract → classify → recommend")
        analyse_card.add(
            hint_label(
                "Analysis reads document text, creates embeddings and proposes a filename and folder. "
                "It never moves anything: recommendations go to the review page first. "
                "Each time OpenCoeus starts the library is empty; scan the folder again."
            )
        )
        analyse_options = FlowLayout()
        self.llm_check = QCheckBox("Use local language model")
        self.llm_check.setChecked(bool(self.ctx.settings.enable_llm))
        self.force_check = QCheckBox("Re-analyse processed and review files")
        analyse_options.addWidget(self.llm_check)
        analyse_options.addWidget(self.force_check)
        analyse_card.add_layout(analyse_options)

        analyse_buttons = FlowLayout()
        self.analyse_button = QPushButton("Analyse pending files")
        self.analyse_button.clicked.connect(self.start_analysis)
        self.analyse_cancel = QPushButton("Cancel")
        self.analyse_cancel.setEnabled(False)
        self.analyse_cancel.clicked.connect(
            lambda: self._analyse_task and self._analyse_task.cancel()
        )
        self.review_button = QPushButton("Review →")
        self.review_button.clicked.connect(lambda: self.navigate.emit("recommendations"))
        analyse_buttons.addWidget(self.analyse_button)
        analyse_buttons.addWidget(self.analyse_cancel)
        analyse_buttons.addWidget(self.review_button)
        analyse_card.add_layout(analyse_buttons)

        self.analyse_progress = QProgressBar()
        self.analyse_progress.setRange(0, 100)
        self.analyse_progress.setValue(0)
        self.analyse_progress.setFixedHeight(8)
        analyse_card.add(self.analyse_progress)
        self.analyse_status = muted_label("Waiting for a scan.")
        analyse_card.add(self.analyse_status)
        layout.addWidget(analyse_card)

        log_card = Card("Activity log")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(600)
        self.log.setPlaceholderText("Scan and analysis messages appear here.")
        self.log.setMinimumHeight(150)
        log_card.add(self.log)
        layout.addWidget(log_card, 1)

        self._log("Ready. Choose a folder to begin.")

    def _browse(self) -> None:
        start = self.ctx.settings.organisation_root
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder to scan", str(start) if start else str(Path.home())
        )
        if folder:
            self.path_edit.setText(folder)

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _on_progress(self, event: object) -> None:
        current = getattr(event, "current", 0)
        total = getattr(event, "total", 0)
        message = getattr(event, "message", "")
        item = getattr(event, "item", None)
        bar = self.scan_progress if getattr(event, "phase", "") == "scan" else self.analyse_progress
        status = self.scan_status if getattr(event, "phase", "") == "scan" else self.analyse_status
        if total:
            bar.setRange(0, total)
            bar.setValue(current)
        else:
            bar.setRange(0, 0)
        prefix = f"{current}/{total} " if total else ""
        status.setText(f"{prefix}{message}")
        if message:
            line = f"{message}" + (f" — {item}" if item else "")
            if not self.log.toPlainText().endswith(line):
                self._log(line)

    def _set_scan_busy(self, busy: bool) -> None:
        self.scan_button.setEnabled(not busy)
        self.scan_cancel.setEnabled(busy)
        self.path_edit.setEnabled(not busy)
        if not busy:
            self.scan_progress.setRange(0, 100)

    def _set_analyse_busy(self, busy: bool) -> None:
        self.analyse_button.setEnabled(not busy)
        self.analyse_cancel.setEnabled(busy)
        if not busy:
            self.analyse_progress.setRange(0, 100)

    def start_scan(self) -> None:
        if self._scan_task is not None and self._scan_task in self._tasks:
            return
        raw = self.path_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Choose a folder", "Pick a folder to scan first.")
            return
        root = Path(raw).expanduser()
        if not root.is_dir():
            QMessageBox.warning(self, "Folder not found", f"{root} is not a readable folder.")
            return

        self._set_scan_busy(True)
        self.scan_progress.setRange(0, 0)
        self._log(f"Scanning {root} …")
        recursive = self.recursive_check.isChecked()
        compute_hashes = self.hash_check.isChecked()
        include_unsupported = self.unsupported_check.isChecked()

        def work(progress, cancel):  # type: ignore[no-untyped-def]
            return self.ctx.scanning.scan(
                root,
                recursive=recursive,
                compute_hashes=compute_hashes,
                include_unsupported=include_unsupported,
                progress=progress,
                cancel=cancel,
            )

        self._scan_task = self.run_task(
            work,
            label="Scan",
            on_done=self._scan_done,
            on_failed=self._scan_failed,
            on_cancelled=lambda: self._on_cancelled("Scan"),
        )

    def _scan_done(self, report: object) -> None:
        self._set_scan_busy(False)
        self.scan_progress.setValue(self.scan_progress.maximum())
        summary = getattr(report, "summary", lambda: "Scan finished.")()
        self.scan_status.setText(summary)
        self._log(summary)
        self._log(f"Organisation root is now {self.ctx.organisation.organisation_root()}")
        self._log("Next: run the analysis pipeline.")
        self.analyse_status.setText("Ready to analyse the files discovered by the scan.")
        self.refresh()
        self.library_changed.emit()

    def _scan_failed(self, error: str) -> None:
        self._set_scan_busy(False)
        self._log(f"Scan failed: {error}")
        QMessageBox.critical(self, "Scan failed", error)

    def start_analysis(self) -> None:
        if self._analyse_task is not None and self._analyse_task in self._tasks:
            return
        self._set_analyse_busy(True)
        self.analyse_progress.setRange(0, 0)
        self._log("Starting analysis …")
        use_llm = self.llm_check.isChecked()
        force = self.force_check.isChecked()

        def work(progress, cancel):  # type: ignore[no-untyped-def]
            return self.ctx.analysis.analyse_pending(
                use_llm=use_llm,
                force=force,
                progress=progress,
                cancel=cancel,
            )

        self._analyse_task = self.run_task(
            work,
            label="Analysis",
            on_done=self._analysis_done,
            on_failed=self._analysis_failed,
            on_cancelled=lambda: self._on_cancelled("Analysis"),
        )

    def _analysis_done(self, report: object) -> None:
        self._set_analyse_busy(False)
        self.analyse_progress.setValue(self.analyse_progress.maximum())
        summary = getattr(report, "summary", lambda: "Analysis finished.")()
        pending_review = getattr(report, "pending_review", 0)
        self.analyse_status.setText(f"{summary} · {pending_review} need review")
        self._log(summary)
        if pending_review:
            self._log(f"{pending_review} file(s) are below the review threshold.")
        errors = getattr(report, "errors", [])
        for file_id, error in errors[:8]:
            self._log(f"  ! file {file_id}: {error}")
        self.review_button.setEnabled(True)
        self.library_changed.emit()

    def _analysis_failed(self, error: str) -> None:
        self._set_analyse_busy(False)
        self._log(f"Analysis failed: {error}")
        QMessageBox.critical(self, "Analysis failed", error)

    def _on_cancelled(self, label: str) -> None:
        if label == "Scan":
            self._set_scan_busy(False)
            self.scan_progress.setRange(0, 100)
            self.scan_status.setText("Scan cancelled; discovered files were kept.")
        else:
            self._set_analyse_busy(False)
            self.analyse_progress.setRange(0, 100)
            self.analyse_status.setText("Analysis cancelled; completed files were kept.")
        self._log(f"{label} cancelled.")
        self.library_changed.emit()

    def refresh(self) -> None:
        root = self.ctx.settings.organisation_root
        if root and not self.path_edit.text().strip():
            self.path_edit.setText(str(root))
        self.llm_check.setChecked(bool(self.ctx.settings.enable_llm))
        has_files = self.ctx.stats().total_files > 0
        for button, primary in (
            (self.scan_button, not has_files),
            (self.analyse_button, has_files),
        ):
            button.setProperty("primary", primary)
            button.style().unpolish(button)
            button.style().polish(button)
