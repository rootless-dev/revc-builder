"""Page 4: one row per stage, an overall progress bar, a collapsible log and Cancel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import label
from vcbuilder.events import Event, LogLine, Progress, StageFailed, StageFinished, StageStarted

#: Stages this page runs (spec section 8: page 4 runs stages 3 to 7) and their share of the bar.
STAGE_WEIGHTS = {"fetch": 10, "deps": 15, "compile": 60, "verify": 5, "install": 10}


class BuildPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        titles = {
            "fetch": self.tr("Download the source code"),
            "deps": self.tr("Build the sound and window libraries"),
            "compile": self.tr("Compile reVC"),
            "verify": self.tr("Check the app"),
            "install": self.tr("Install the app and the game data"),
        }
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(label(self.tr("Building"), "Heading"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for row, stage in enumerate(STAGE_WEIGHTS):
            marker = QLabel("○")
            marker.setObjectName("Muted")
            name = label(titles[stage], wrap=False)
            grid.addWidget(marker, row, 0)
            grid.addWidget(name, row, 1)
            self.rows[stage] = (marker, name)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self.overall = QProgressBar()
        self.overall.setRange(0, 1000)
        self.overall.setTextVisible(False)
        layout.addWidget(self.overall)
        self.status_label = label("", "Muted")
        layout.addWidget(self.status_label)

        self.log_toggle = QPushButton(self.tr("Show log"))
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.hide()
        layout.addWidget(self.log_view, 1)
        layout.addStretch(0)

        buttons = QHBoxLayout()
        buttons.addWidget(self.log_toggle)
        buttons.addStretch(1)
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self._done: set[str] = set()
        self._current: str | None = None
        self._fraction = 0.0

    def reset(self, start: str = "fetch") -> None:
        """Prepare for a run from ``start``; earlier stages count as done."""
        stages = list(STAGE_WEIGHTS)
        self._done = set(stages[: stages.index(start)]) if start in stages else set()
        self._current = None
        self._fraction = 0.0
        for stage, (marker, _name) in self.rows.items():
            marker.setText("✓" if stage in self._done else "○")
        self.status_label.setText("")
        self.cancel_button.setEnabled(True)
        self._update_overall()

    def _toggle_log(self, shown: bool) -> None:
        self.log_view.setVisible(shown)
        self.log_toggle.setText(self.tr("Hide log") if shown else self.tr("Show log"))

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.status_label.setText(self.tr("Cancelling…"))
        self.cancel_requested.emit()

    def handle_event(self, event: Event) -> None:
        stage = getattr(event, "stage", None)
        if isinstance(event, LogLine):
            self.log_view.appendPlainText(event.text)
            return
        if stage not in self.rows:
            return
        marker = self.rows[stage][0]
        if isinstance(event, StageStarted):
            self._current, self._fraction = stage, 0.0
            marker.setText("▶")
        elif isinstance(event, Progress):
            if event.fraction is not None:
                self._fraction = max(0.0, min(1.0, event.fraction))
            if event.message:
                self.status_label.setText(event.message)
        elif isinstance(event, StageFinished):
            self._done.add(stage)
            self._current, self._fraction = None, 0.0
            marker.setText("✓")
        elif isinstance(event, StageFailed):
            marker.setText("–" if event.cancelled else "✕")
            self._current = None
            self.cancel_button.setEnabled(False)
            if event.cancelled:
                self.status_label.setText(self.tr("Cancelled."))
        self._update_overall()

    def _update_overall(self) -> None:
        total = sum(STAGE_WEIGHTS.values())
        done = sum(STAGE_WEIGHTS[stage] for stage in self._done)
        if self._current:
            done += STAGE_WEIGHTS[self._current] * self._fraction
        self.overall.setValue(int(round(1000 * done / total)))
