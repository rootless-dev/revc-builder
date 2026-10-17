"""Page 2: choose the game folder (dialog, drop area or a detected Steam install)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import label
from vcbuilder.gamefiles import ValidationResult, ValidationStatus


class DropArea(QFrame):
    folder_dropped = Signal(Path)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        layout = QVBoxLayout(self)
        hint = label(text, "Muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

    def _set_hover(self, hover: bool) -> None:
        self.setProperty("hover", "true" if hover else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def _folder(event) -> Path | None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        for url in urls:
            if url.isLocalFile() and Path(url.toLocalFile()).is_dir():
                return Path(url.toLocalFile())
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._folder(event):
            self._set_hover(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)
        folder = self._folder(event)
        if folder:
            event.acceptProposedAction()
            self.folder_dropped.emit(folder)


class GameFilesPage(QWidget):
    accepted = Signal(Path)
    back_requested = Signal()

    def __init__(self, engine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.folder: Path | None = None
        self.installed_game: Path | None = None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label(self.tr("Game files"), "Heading"))
        layout.addWidget(label(self.tr(
            "Choose the folder where GTA Vice City is installed: the one that contains the "
            "data and models folders. Not the installer or the downloaded archive."
        )))

        row = QHBoxLayout()
        self.choose_button = QPushButton(self.tr("Choose folder…"))
        self.choose_button.clicked.connect(self._open_dialog)
        row.addWidget(self.choose_button)
        self.installed_button = QPushButton(self.tr("Use the game already installed"))
        self.installed_button.setToolTip(self.tr(
            "The copy of the game made by an earlier build. Nothing is copied again."
        ))
        self.installed_button.clicked.connect(self._installed_chosen)
        row.addWidget(self.installed_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.drop_area = DropArea(self.tr("…or drag the game folder here"))
        self.drop_area.folder_dropped.connect(self.choose_folder)
        layout.addWidget(self.drop_area)

        self.steam_heading = label(self.tr("Steam installs found on this Mac:"), "Muted")
        self.steam_list = QListWidget()
        self.steam_list.setMaximumHeight(80)
        self.steam_list.itemActivated.connect(self._steam_chosen)
        self.steam_list.itemClicked.connect(self._steam_chosen)
        layout.addWidget(self.steam_heading)
        layout.addWidget(self.steam_list)

        self.folder_label = label("", "Muted")
        self.result_label = label("")
        layout.addWidget(self.folder_label)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.back_button = QPushButton(self.tr("Back"))
        self.back_button.clicked.connect(self.back_requested)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        self.next_button = QPushButton(self.tr("Continue"))
        self.next_button.setObjectName("Primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self._continue)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    def refresh_sources(self) -> None:
        """Refresh the offered sources and, the first time, pick the folder used last time."""
        self.refresh_steam_installs()
        self.installed_game = self.engine.installed_game_folder()
        self.installed_button.setVisible(self.installed_game is not None)
        if self.folder is None:
            remembered = self.engine.remembered_game_folder()
            if remembered is not None:
                self.choose_folder(remembered)

    def _installed_chosen(self) -> None:
        if self.installed_game is not None:
            self.choose_folder(self.installed_game)

    def refresh_steam_installs(self) -> None:
        self.steam_list.clear()
        installs = self.engine.steam_installs()
        for path in installs:
            item = QListWidgetItem(str(path))
            item.setData(Qt.UserRole, str(path))
            self.steam_list.addItem(item)
        visible = bool(installs)
        self.steam_heading.setVisible(visible)
        self.steam_list.setVisible(visible)

    def _open_dialog(self) -> None:
        start = str(self.folder or Path.home())
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Choose the game folder"), start)
        if chosen:
            self.choose_folder(Path(chosen))

    def _steam_chosen(self, item: QListWidgetItem) -> None:
        self.choose_folder(Path(item.data(Qt.UserRole)))

    def choose_folder(self, folder: Path) -> None:
        """Validate ``folder`` at once and show the result inline (spec section 6.2)."""
        self.folder = Path(folder)
        self.folder_label.setText(str(self.folder))
        result = self.engine.validate(self.folder)
        self._show_result(result)

    def _show_result(self, result: ValidationResult) -> None:
        if result.status is ValidationStatus.VALID:
            self.result_label.setObjectName("Good")
            self.result_label.setText(self.tr("✓ All required game files are present."))
        elif result.status is ValidationStatus.BUILDER_FOLDER:
            self.result_label.setObjectName("Bad")
            self.result_label.setText(self.tr(
                "This folder is used by the Builder itself. Choose the original game folder."
            ))
        elif result.status is ValidationStatus.INSTALLER:
            self.result_label.setObjectName("Bad")
            self.result_label.setText(self.tr(
                "This looks like a game installer, not an installed game. Install the game "
                "first, then choose the folder where it was installed."
            ))
        elif result.status is ValidationStatus.NOT_GAME_FOLDER:
            self.result_label.setObjectName("Bad")
            self.result_label.setText(self.tr(
                "This is not a game folder. Choose the folder that contains the data and models folders."
            ))
        else:
            self.result_label.setObjectName("Bad")
            shown = "\n".join(f"  • {path}" for path in result.shown_missing)
            more = len(result.missing) - len(result.shown_missing)
            text = self.tr("The game folder is incomplete. Missing files:") + "\n" + shown
            if more > 0:
                text += "\n" + self.tr("…and %n more (see the log).", "", more)
            self.result_label.setText(text)
        self.result_label.style().unpolish(self.result_label)
        self.result_label.style().polish(self.result_label)
        self.next_button.setEnabled(result.is_valid)

    def _continue(self) -> None:
        if self.folder is not None and self.next_button.isEnabled():
            self.accepted.emit(self.folder)
