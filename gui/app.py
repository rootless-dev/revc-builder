"""reVC Builder: the single-window wizard (spec section 7).

The GUI never runs a command itself. Every build operation goes through the engine (a
``vcbuilder.session.BuildSession``); apart from its own style, font and translation files,
the only direct system access is Qt's folder dialog, drag and drop, the clipboard and
``QDesktopServices``.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QObject, Qt, QTranslator, Signal
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from gui.pages.build import BuildPage
from gui.pages.done import DonePage
from gui.pages.error import ErrorPage
from gui.pages.game_files import GameFilesPage
from gui.pages.tools import ToolsPage
from gui.pages.welcome import WelcomePage
from gui.widgets import CYAN, SunsetBanner, glow, label
from vcbuilder.errors import BuildError
from vcbuilder.events import Event, StageFailed
from vcbuilder.pipeline import PipelineResult

GUI_DIR = Path(__file__).resolve().parent
STYLE_DIR = GUI_DIR / "style"
I18N_DIR = GUI_DIR / "i18n"
TRANSLATION_NAME = "revc_builder"


class BuildRunner(QObject):
    """Runs ``engine.build`` on a worker thread and relays its events to the GUI thread."""

    event = Signal(object)
    finished = Signal(object)

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._thread: threading.Thread | None = None
        engine.subscribe(self.event.emit)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, folder: Path, start: str) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, args=(folder, start), name="vcbuilder", daemon=True)
        self._thread.start()

    def _run(self, folder: Path, start: str) -> None:
        try:
            result = self.engine.build(folder, start=start)
        except Exception as unexpected:  # never leave the Build page waiting forever
            result = PipelineResult(False, start, BuildError(f"{type(unexpected).__name__}: {unexpected}"))
        self.finished.emit(result)

    def cancel(self) -> None:
        self.engine.cancel()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


class MainWindow(QMainWindow):
    def __init__(self, engine, *, tools_poll_ms: int | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.folder: Path | None = None
        self.failed_stage: str | None = None
        self.setWindowTitle(self.tr("reVC Builder"))
        self.setFixedSize(780, 620)

        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(SunsetBanner(height=110))

        content = QVBoxLayout()
        content.setContentsMargins(36, 10, 36, 26)
        title = glow(label("reVC Builder", "Title", wrap=False))
        title.setAlignment(Qt.AlignHCenter)
        content.addWidget(title)
        self.steps_label = label("", "Steps", wrap=False)
        self.steps_label.setAlignment(Qt.AlignHCenter)
        content.addWidget(self.steps_label)

        self.stack = QStackedWidget()
        self.welcome = WelcomePage()
        self.game_files = GameFilesPage(engine)
        self.tools = ToolsPage(engine, **({"poll_ms": tools_poll_ms} if tools_poll_ms else {}))
        self.build = BuildPage()
        self.done = DonePage()
        self.error = ErrorPage(engine)
        for page in (self.welcome, self.game_files, self.tools, self.build, self.done, self.error):
            self.stack.addWidget(page)
        content.addWidget(self.stack, 1)
        outer.addLayout(content, 1)
        self.setCentralWidget(root)

        self.runner = BuildRunner(engine, self)
        self.runner.event.connect(self._on_event)
        self.runner.finished.connect(self._on_finished)

        self.welcome.started.connect(self._show_game_files)
        self.game_files.back_requested.connect(lambda: self._show(self.welcome))
        self.game_files.accepted.connect(self._folder_accepted)
        self.tools.back_requested.connect(self._show_game_files)
        self.tools.ready.connect(lambda: self._start_build("fetch"))
        self.build.cancel_requested.connect(self.runner.cancel)
        self.error.retry_requested.connect(self._retry)
        self.done.quit_requested.connect(self.close)
        self._show(self.welcome)

    # navigation -----------------------------------------------------------------------------

    def current_page(self) -> QWidget:
        return self.stack.currentWidget()

    def _step_names(self) -> list[tuple[QWidget, str]]:
        return [
            (self.welcome, self.tr("Welcome")),
            (self.game_files, self.tr("Game files")),
            (self.tools, self.tr("Tools")),
            (self.build, self.tr("Build")),
            (self.done, self.tr("Done")),
        ]

    def _show(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        highlighted = self.build if page is self.error else page
        parts = []
        for step, name in self._step_names():
            parts.append(f"<span style='color:{CYAN.name()}'>{name}</span>" if step is highlighted else name)
        self.steps_label.setText("  ·  ".join(parts))

    def _show_game_files(self) -> None:
        self.game_files.refresh_sources()
        self._show(self.game_files)

    def _folder_accepted(self, folder: Path) -> None:
        self.folder = folder
        self.engine.remember_game_folder(folder)
        self._show(self.tools)
        self.tools.check()

    def _start_build(self, start: str) -> None:
        if self.folder is None:
            return
        self.build.reset(start)
        self._show(self.build)
        self.runner.start(self.folder, start)

    def _retry(self) -> None:
        self._start_build(self.failed_stage or "fetch")

    # engine events --------------------------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        self.build.handle_event(event)
        if isinstance(event, StageFailed) and not event.cancelled:
            self.failed_stage = event.stage

    def _on_finished(self, result) -> None:
        if result.succeeded:
            self.done.set_app(getattr(self.engine, "installed_app", None))
            self._show(self.done)
        elif result.cancelled:
            self.failed_stage = result.failed_stage
            self.error.show_cancelled()
            self._show(self.error)
        else:
            self.failed_stage = result.failed_stage
            self.error.show_error(result.error)
            self._show(self.error)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.runner.running:
            self.runner.cancel()
            self.runner.wait(10)
        self.tools.timer.stop()
        super().closeEvent(event)


# --- application setup ---------------------------------------------------------------------------


def load_fonts() -> None:
    for font in sorted(STYLE_DIR.glob("fonts/*/*.ttf")):
        QFontDatabase.addApplicationFont(str(font))


def load_style_sheet() -> str:
    return (STYLE_DIR / "theme.qss").read_text(encoding="utf-8")


def install_translator(app: QApplication, locale: QLocale | None = None) -> QTranslator | None:
    """Load the translation for ``locale`` (default: the system language); English needs none."""
    translator = QTranslator(app)
    if translator.load(locale or QLocale.system(), TRANSLATION_NAME, "_", str(I18N_DIR)):
        app.installTranslator(translator)
        return translator
    return None


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("reVC Builder")
    app.setOrganizationName("reVC Builder")
    icon = STYLE_DIR / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    load_fonts()
    app.setStyleSheet(load_style_sheet())
    install_translator(app)
    return app


def main() -> int:
    from vcbuilder.errors import UnsupportedPlatformError
    from vcbuilder.session import BuildSession

    app = create_application()
    try:
        engine = BuildSession()
    except UnsupportedPlatformError:
        QMessageBox.critical(
            None,
            "reVC Builder",
            QCoreApplication.translate("MainWindow", "This operating system is not supported yet. reVC Builder currently runs on macOS only."),
        )
        return 1
    window = MainWindow(engine)
    window.show()
    try:
        return app.exec()
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
