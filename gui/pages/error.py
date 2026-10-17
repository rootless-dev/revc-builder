"""Shown in place of a page when a stage fails: a plain message, Copy log and Try again."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLocale, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from gui.widgets import label
from vcbuilder.errors import BuildError


def _messages() -> dict[str, str]:
    # Literal QCoreApplication.translate calls, so pyside6-lupdate can collect them.
    return {
        "source_unavailable": QCoreApplication.translate("ErrorPage", "Could not download the source code. Check your internet connection."),
        "integrity": QCoreApplication.translate("ErrorPage", "The downloaded code did not match the expected version and was discarded for safety."),
        "compile": QCoreApplication.translate("ErrorPage", "The build failed. Copy the log and include it when asking for help."),
        "bundle": QCoreApplication.translate("ErrorPage", "The build failed. Copy the log and include it when asking for help."),
        "disk_space": QCoreApplication.translate("ErrorPage", "Not enough free space: %1 GB needed on %2."),
        "not_game_folder": QCoreApplication.translate("ErrorPage", "Not a game folder. Choose the folder that contains the data and models folders."),
        "incomplete_game": QCoreApplication.translate("ErrorPage", "The game folder is incomplete. Copy the log to see every missing file."),
        "tools_missing": QCoreApplication.translate("ErrorPage", "The Apple Command Line Tools are not installed."),
        "clang_failed": QCoreApplication.translate(
            "ErrorPage",
            "The Command Line Tools are installed, but the compiler does not run. If Xcode is "
            "installed, open it once and accept its licence, then try again."
        ),
        "install": QCoreApplication.translate("ErrorPage", "Could not install the game. Copy the log and include it when asking for help."),
        "install_overlap": QCoreApplication.translate(
            "ErrorPage", "Choose the original game folder, not a folder used by the Builder itself."
        ),
        "lock": QCoreApplication.translate("ErrorPage", "The list of pinned sources is damaged. Download the Builder again."),
        "internal": QCoreApplication.translate("ErrorPage", "Something went wrong. Copy the log and include it when asking for help."),
    }


def user_message(error: BuildError | None) -> str:
    messages = _messages()
    if error is None:
        return messages["internal"]
    text = messages.get(error.code)
    if text is None:
        return error.user_message
    if error.code == "disk_space":
        needed = QLocale().toString(float(error.params.get("needed_bytes", 0)) / 1e9, "f", 1)
        volume = (
            QCoreApplication.translate("ErrorPage", "the startup disk")
            if error.params.get("startup_disk")
            else str(error.params.get("volume", "?"))
        )
        text = text.replace("%1", needed).replace("%2", volume)
    return text


class ErrorPage(QWidget):
    retry_requested = Signal()

    def __init__(self, engine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.heading_label = label(self.tr("Something went wrong"), "Heading")
        layout.addWidget(self.heading_label)
        self.message_label = label("")
        layout.addWidget(self.message_label)
        self.copied_label = label("", "Muted")
        layout.addWidget(self.copied_label)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton(self.tr("Copy log"))
        self.copy_button.clicked.connect(self.copy_log)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        self.retry_button = QPushButton(self.tr("Try again"))
        self.retry_button.setObjectName("Primary")
        self.retry_button.clicked.connect(self.retry_requested)
        buttons.addWidget(self.retry_button)
        layout.addLayout(buttons)

    def show_error(self, error: BuildError | None) -> None:
        self.heading_label.setText(self.tr("Something went wrong"))
        self.message_label.setText(user_message(error))
        self.copied_label.setText("")

    def show_cancelled(self) -> None:
        self.heading_label.setText(self.tr("Build cancelled"))
        self.message_label.setText(self.tr("The build was cancelled. You can continue where it stopped."))
        self.copied_label.setText("")

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.engine.log_text())
        self.copied_label.setText(self.tr("The log is on the clipboard."))
