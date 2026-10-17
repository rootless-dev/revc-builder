"""Page 5: where the app went, Play, and Show in Finder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from gui.widgets import label


class DonePage(QWidget):
    quit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_path: Path | None = None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label(self.tr("Ready to play"), "Heading"))
        self.location_label = label("")
        layout.addWidget(self.location_label)
        layout.addWidget(label(self.tr(
            "The first time you open it, macOS may ask for confirmation because the app was built "
            "on this Mac and is not notarized."
        ), "Muted"))
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.finder_button = QPushButton(self.tr("Show in Finder"))
        self.finder_button.clicked.connect(self.show_in_finder)
        buttons.addWidget(self.finder_button)
        self.quit_button = QPushButton(self.tr("Quit"))
        self.quit_button.clicked.connect(self.quit_requested)
        buttons.addWidget(self.quit_button)
        buttons.addStretch(1)
        self.play_button = QPushButton(self.tr("Play"))
        self.play_button.setObjectName("Primary")
        self.play_button.clicked.connect(self.play)
        buttons.addWidget(self.play_button)
        layout.addLayout(buttons)

    def set_app(self, app_path: Path | None) -> None:
        self.app_path = app_path
        self.location_label.setText(self.tr("reVC is installed at %1.").replace("%1", str(app_path)))

    def play(self) -> None:
        # LaunchServices starts it exactly like a Finder double-click (spec section 6.4).
        if self.app_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.app_path)))

    def show_in_finder(self) -> None:
        if self.app_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.app_path.parent)))
