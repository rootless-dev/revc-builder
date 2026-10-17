"""Page 3: the build tools (spec section 7; on macOS, the Apple Command Line Tools).

``check_tools`` runs the platform's cheap presence check and only then the compiler; while
waiting for an install, the page polls ``tools_present`` alone, so the compiler never runs
before the tools exist (on macOS, running clang without them opens Apple's dialog).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from gui.widgets import label
from vcbuilder.platform.base import POLL_INTERVAL, ToolsStatus


class ToolsPage(QWidget):
    ready = Signal()
    back_requested = Signal()

    def __init__(self, engine, parent: QWidget | None = None, poll_ms: int = int(POLL_INTERVAL * 1000)) -> None:
        super().__init__(parent)
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label(self.tr("Developer tools"), "Heading"))
        layout.addWidget(label(self.tr(
            "Compiling the game needs Apple's free Command Line Tools. If they are missing, "
            "macOS installs them for you in a standard window."
        )))
        self.status_label = label("")
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        self.install_button = QPushButton(self.tr("Install"))
        self.install_button.setObjectName("Primary")
        self.install_button.clicked.connect(self._install)
        self.cancel_wait_button = QPushButton(self.tr("Stop waiting"))
        self.cancel_wait_button.clicked.connect(self._stop_waiting)
        self.check_again_button = QPushButton(self.tr("Check again"))
        self.check_again_button.clicked.connect(self.check)
        for button in (self.install_button, self.cancel_wait_button, self.check_again_button):
            row.addWidget(button)
            button.hide()
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.back_button = QPushButton(self.tr("Back"))
        self.back_button.clicked.connect(self._back)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        self.next_button = QPushButton(self.tr("Build the game"))
        self.next_button.setObjectName("Primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.ready)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setInterval(poll_ms)
        self.timer.timeout.connect(self._poll)

    def _show_buttons(self, *visible: QPushButton) -> None:
        for button in (self.install_button, self.cancel_wait_button, self.check_again_button):
            button.setVisible(button in visible)

    def check(self) -> None:
        self.timer.stop()
        self.next_button.setEnabled(False)
        self.status_label.setText(self.tr("Checking…"))
        status = self.engine.check_tools()
        if status is ToolsStatus.READY:
            self.status_label.setObjectName("Good")
            self.status_label.setText(self.tr("✓ The Command Line Tools are installed."))
            self._show_buttons()
            self.next_button.setEnabled(True)
        elif status is ToolsStatus.MISSING:
            self.status_label.setObjectName("Body")
            self.status_label.setText(self.tr("The Command Line Tools are not installed yet."))
            self._show_buttons(self.install_button)
        else:
            self.status_label.setObjectName("Bad")
            self.status_label.setText(self.tr(
                "The tools are installed, but the compiler does not start. This usually means Xcode "
                "is installed and its licence has not been accepted yet. Open Xcode once, accept the "
                "licence, then check again."
            ))
            self._show_buttons(self.check_again_button)
        self._repolish()

    def _install(self) -> None:
        self.engine.request_tools_install()
        self.status_label.setObjectName("Body")
        self.status_label.setText(self.tr(
            "Follow the instructions in the window macOS opened. This page continues by itself "
            "when the installation finishes."
        ))
        self._repolish()
        self._show_buttons(self.cancel_wait_button)
        self.timer.start()

    def _poll(self) -> None:
        if self.engine.tools_present():
            self.timer.stop()
            self.check()

    def _stop_waiting(self) -> None:
        self.timer.stop()
        self.status_label.setText(self.tr("Stopped waiting for the installation."))
        self._show_buttons(self.install_button, self.check_again_button)

    def _back(self) -> None:
        self.timer.stop()
        self.back_requested.emit()

    def _repolish(self) -> None:
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
