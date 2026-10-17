"""Page 1: what the tool does, and that the user must own the game."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from gui.widgets import label


class WelcomePage(QWidget):
    started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(label(self.tr("Welcome"), "Heading"))
        layout.addWidget(label(self.tr(
            "This app turns your copy of GTA Vice City for Windows into a game that runs natively "
            "on this Mac. It downloads the reVC source code, compiles it here, and installs reVC.app "
            "in your Applications folder."
        )))
        layout.addWidget(label(self.tr(
            "You need your own game files: the folder of an installed PC copy, for example from Steam. "
            "No game files are included, and none are sent anywhere."
        )))
        layout.addWidget(label(self.tr(
            "The build takes a few minutes. It needs an internet connection and about 500 MB of "
            "free space, plus the size of the game."
        ), "Muted"))
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.start_button = QPushButton(self.tr("Get started"))
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.started)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
