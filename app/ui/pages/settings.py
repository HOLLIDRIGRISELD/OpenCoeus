"""Settings page: typed preferences, local model configuration and capabilities."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from app.ui.base import BasePage
from app.ui.theme import AMBER, GREEN, RED
from app.ui.widgets import (
    Card,
    LineEdit,
    add_actions,
    hint_label,
    make_table,
    muted_label,
    scrollable_page,
    set_cell,
)

TEMPLATE_TOKENS = "{title}, {category}, {subject}, {document_type}, {organisation}, {date}, {year}, {original}"


class SettingsPage(BasePage):
    """Everything configurable, with validation and a capability report."""

    settings_changed = Signal()
    library_changed = Signal()

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        self.save_button = QPushButton("Save settings")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(self._save)
        top = add_actions(layout, self.save_button)
        top.insertWidget(
            0,
            muted_label("Settings are stored locally in SQLite and apply immediately on save."),
            1,
        )

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self._settings_grid = grid
        self._settings_cards = [
            self._build_organisation_card(),
            self._build_search_card(),
            self._build_models_card(),
            self._build_limits_card(),
        ]
        self._capabilities_card = self._build_capabilities_card()
        self._settings_columns: int | None = None
        layout.addLayout(grid)

        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        layout.addStretch(1)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._relayout_settings()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._relayout_settings()

    def _relayout_settings(self) -> None:
        """Collapse the two-column card grid into one on narrow screens."""

        columns = 2 if self.width() >= 980 else 1
        if columns == self._settings_columns:
            return
        self._settings_columns = columns
        while self._settings_grid.count():
            self._settings_grid.takeAt(0)
        for row in range(self._settings_grid.rowCount() + 2):
            self._settings_grid.setRowStretch(row, 0)
        for index, card in enumerate(self._settings_cards):
            self._settings_grid.addWidget(card, index // columns, index % columns)
        cap_row = (len(self._settings_cards) + columns - 1) // columns
        self._settings_grid.addWidget(self._capabilities_card, cap_row, 0, 1, columns)
        self._settings_grid.setRowStretch(cap_row + 1, 1)

    def _build_organisation_card(self) -> Card:
        card = Card("Organisation & naming", subtitle="where plans are resolved from")
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        root_row = QHBoxLayout()
        self.root_edit = LineEdit()
        self.root_edit.setPlaceholderText("Leave empty to use the most recent scan root")
        root_row.addWidget(self.root_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(browse)
        root_widget = QWidget()
        root_widget.setLayout(root_row)
        root_row.setContentsMargins(0, 0, 0, 0)
        form.addRow(self._label("Root"), root_widget)

        self.template_edit = LineEdit()
        self.template_edit.setPlaceholderText("{title}")
        form.addRow(self._label("Filename template"), self.template_edit)
        form.addRow(hint_label(f"Available tokens: {TEMPLATE_TOKENS}"))

        self.high_spin = self._percent_spin(0.85)
        form.addRow(self._label("High-confidence threshold"), self.high_spin)
        self.low_spin = self._percent_spin(0.60)
        form.addRow(self._label("Review threshold"), self.low_spin)
        form.addRow(
            hint_label(
                "Below the review threshold a file is marked for human review. The review "
                "threshold must be lower than the high-confidence threshold."
            )
        )
        card.add_layout(form)
        card.body.addStretch(1)
        return card

    def _build_search_card(self) -> Card:
        card = Card("Search", subtitle="Reciprocal Rank Fusion weights")
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.alpha_spin = self._percent_spin(0.40)
        form.addRow(self._label("Keyword weight (alpha)"), self.alpha_spin)
        self.beta_spin = self._percent_spin(0.60)
        form.addRow(self._label("Semantic weight (beta)"), self.beta_spin)
        form.addRow(
            hint_label(
                "Weights need not sum to one; only their ratio matters. Keyword search is "
                "literal, semantic search compares chunk embeddings, and hybrid fuses both."
            )
        )
        card.add_layout(form)
        card.body.addStretch(1)
        return card

    def _build_models_card(self) -> Card:
        card = Card("Local models", subtitle="optional components degrade gracefully")
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.embedding_edit = LineEdit()
        form.addRow(self._label("Embedding model"), self.embedding_edit)
        self.prefer_transformer = QCheckBox("Prefer a trained model")
        form.addRow(self.prefer_transformer)
        form.addRow(
            hint_label(
                "Uses sentence-transformers when installed, otherwise a deterministic "
                "hashing embedder. No model is downloaded automatically."
            )
        )
        self.llm_enabled = QCheckBox("Local model tie-breaker")
        form.addRow(self.llm_enabled)
        form.addRow(hint_label("Only consulted when classification is inconclusive."))
        self.llm_model_edit = LineEdit()
        form.addRow(self._label("LLM model"), self.llm_model_edit)
        self.llm_url_edit = LineEdit()
        form.addRow(self._label("LLM endpoint"), self.llm_url_edit)
        form.addRow(
            hint_label(
                "The language model never touches the filesystem. Its output is validated and "
                "can only adjust an inconclusive classification or propose a title. The Ollama "
                "tray app opens and closes with OpenCoeus; pull the model once."
            )
        )
        card.add_layout(form)
        card.body.addStretch(1)
        return card

    def _build_limits_card(self) -> Card:
        card = Card("Limits & storage", subtitle="tune behaviour on large libraries")
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(1, 10_000)
        self.max_size_spin.setSuffix(" MB")
        form.addRow(self._label("Maximum analysis size"), self.max_size_spin)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 1000)
        form.addRow(self._label("Scan progress batch"), self.batch_spin)
        self.data_dir_label = QLabel("")
        self.data_dir_label.setProperty("role", "hint")
        self.data_dir_label.setWordWrap(True)
        form.addRow(self._label("Data directory"), self.data_dir_label)
        card.add_layout(form)
        card.body.addStretch(1)
        return card

    def _build_capabilities_card(self) -> Card:
        card = Card("Capabilities", subtitle="what is available on this machine")
        self.capability_table = make_table(
            ["Capability", "Status", "Detail"],
            stretch=2,
        )
        self.capability_table.setMinimumHeight(150)
        card.add(self.capability_table)
        row = QHBoxLayout()
        self.probe_button = QPushButton("Probe models")
        self.probe_button.clicked.connect(self._probe)
        row.addWidget(self.probe_button)
        row.addStretch(1)
        card.add_layout(row)
        self.fallback_label = hint_label("")
        card.add(self.fallback_label)
        return card

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "field")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _percent_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.01, 0.99)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        return spin

    def refresh(self) -> None:
        snapshot = self.ctx.settings.snapshot()
        self.root_edit.setText(str(snapshot.get("organisation.root") or ""))
        self.template_edit.setText(str(snapshot["app.naming_template"]))
        self.high_spin.setValue(float(snapshot["app.high_confidence"]))
        self.low_spin.setValue(float(snapshot["app.low_confidence"]))
        self.alpha_spin.setValue(float(snapshot["search.alpha"]))
        self.beta_spin.setValue(float(snapshot["search.beta"]))
        self.embedding_edit.setText(str(snapshot["embeddings.model"]))
        self.prefer_transformer.setChecked(bool(snapshot["app.prefer_transformer"]))
        self.llm_enabled.setChecked(bool(snapshot["app.enable_llm"]))
        self.llm_model_edit.setText(str(snapshot["llm.model"]))
        self.llm_url_edit.setText(str(snapshot["llm.base_url"]))
        self.max_size_spin.setValue(int(snapshot["app.max_file_size_mb"]))
        self.batch_spin.setValue(int(snapshot["app.scan_batch_size"]))
        self.data_dir_label.setText(str(self.ctx.config.data_dir))
        self._refresh_capabilities(probe=False)
        self.fallback_label.setText(
            "Fallbacks: "
            + "; ".join(
                f"{key}: {value}" for key, value in self.ctx.models.fallbacks.items()
            )
        )
        self.feedback.setText("")

    def _refresh_capabilities(self, *, probe: bool) -> None:
        try:
            statuses = self.ctx.capabilities(probe=probe)
        except Exception as exc:
            self.message.emit(f"Could not read capabilities: {exc}")
            return
        self._render_capabilities(statuses)

    def _render_capabilities(self, statuses: list[object]) -> None:
        self.capability_table.setRowCount(0)
        for row, capability in enumerate(statuses):
            self.capability_table.insertRow(row)
            set_cell(self.capability_table, row, 0, capability.label)
            if capability.available:
                state, colour = "ready", GREEN
            elif capability.required:
                state, colour = "required", RED
            else:
                state, colour = "optional", AMBER
            set_cell(self.capability_table, row, 1, state, color=colour)
            set_cell(self.capability_table, row, 2, capability.detail)

    def _browse_root(self) -> None:
        current = self.root_edit.text().strip()
        start = current if current and Path(current).is_dir() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose the organisation root", start)
        if folder:
            self.root_edit.setText(folder)

    def _values(self) -> dict[str, object]:
        return {
            "organisation.root": self.root_edit.text().strip(),
            "app.naming_template": self.template_edit.text().strip(),
            "app.high_confidence": self.high_spin.value(),
            "app.low_confidence": self.low_spin.value(),
            "search.alpha": self.alpha_spin.value(),
            "search.beta": self.beta_spin.value(),
            "embeddings.model": self.embedding_edit.text().strip(),
            "app.prefer_transformer": self.prefer_transformer.isChecked(),
            "app.enable_llm": self.llm_enabled.isChecked(),
            "llm.model": self.llm_model_edit.text().strip(),
            "llm.base_url": self.llm_url_edit.text().strip(),
            "app.max_file_size_mb": self.max_size_spin.value(),
            "app.scan_batch_size": self.batch_spin.value(),
        }

    def _save(self) -> None:
        values = self._values()
        root = str(values["organisation.root"])
        if root and not Path(root).expanduser().is_dir():
            self._feedback(f"Organisation root is not a folder: {root}", RED)
            return
        if not str(values["embeddings.model"]):
            self._feedback("The embedding model name cannot be empty.", RED)
            return
        try:
            problems = self.ctx.apply_settings(values)
        except Exception as exc:
            self._feedback(f"Settings could not be saved: {exc}", RED)
            return
        if problems:
            self._feedback(" ".join(problems), RED)
            QMessageBox.warning(self, "Settings not saved", "\n".join(problems))
            return
        self._feedback("Settings saved and applied. New analyses use the updated values.", GREEN)
        self.message.emit("Settings saved.")
        self.refresh()
        self.settings_changed.emit()
        self.library_changed.emit()

    def _probe(self) -> None:
        self.probe_button.setEnabled(False)
        self.probe_button.setText("Probing…")

        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.capabilities(probe=True)

        def done(statuses: object) -> None:
            self.probe_button.setEnabled(True)
            self.probe_button.setText("Probe models")
            if isinstance(statuses, list):
                self._render_capabilities(statuses)
            self.message.emit("Capability probe finished.")

        def failed(error: str) -> None:
            self.probe_button.setEnabled(True)
            self.probe_button.setText("Probe models")
            self.message.emit(f"Capability probe failed: {error}")

        self.run_task(work, label="Capability probe", on_done=done, on_failed=failed)

    def _feedback(self, text: str, colour: str) -> None:
        self.feedback.setText(text)
        self.feedback.setStyleSheet(f"color: {colour};")
        if colour == RED:
            self.message.emit(text)


__all__ = ["SettingsPage"]
