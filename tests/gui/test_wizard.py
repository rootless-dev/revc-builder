"""GUI tests (spec section 11) with a fake engine; nothing here builds anything."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QLocale, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.app import MainWindow, install_translator  # noqa: E402
from tests.conftest import FakeRunner, make_tree  # noqa: E402
from vcbuilder.errors import CompileError  # noqa: E402
from vcbuilder.events import LogLine, Progress, StageFailed, StageFinished, StageStarted  # noqa: E402
from vcbuilder.gamefiles import validate_game_folder  # noqa: E402
from vcbuilder.pipeline import PipelineResult  # noqa: E402
from vcbuilder.platform.macos import MacOSPlatform  # noqa: E402

MACOS = MacOSPlatform()

BUILD_STAGES = ("fetch", "deps", "compile", "verify", "install")


class FakeEngine:
    """Implements the BuildSession surface the GUI uses, with scripted results.

    Tool checks go through the real macOS platform implementation over a FakeRunner,
    so the tests can see exactly which commands the Tools page caused.
    """

    def __init__(self, tmp_path: Path, *, xcode_select_ok=True, clang_ok=True, fail_stage=None, cancel_stage=None):
        self.cancel_stage = cancel_stage
        self.tmp_path = tmp_path
        self.xcode_select_ok = xcode_select_ok
        self.clang_ok = clang_ok
        self.fail_stage = fail_stage
        self.listeners = []
        self.runner = FakeRunner(responder=self._respond)
        self.builds = []
        self.installed_app = None
        self.cancelled = False

    def _respond(self, argv):
        if argv[:2] == ("/usr/bin/xcode-select", "-p"):
            return (0, "/Library/Developer/CommandLineTools") if self.xcode_select_ok else (2, "not installed")
        if argv[0] == "/usr/bin/clang":
            return (0, "Apple clang") if self.clang_ok else (69, "licence not accepted")
        return 0, ""

    def ran_clang(self):
        return any(command[0] == "/usr/bin/clang" for command in self.runner.commands())

    def subscribe(self, listener):
        self.listeners.append(listener)

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def validate(self, folder):
        return validate_game_folder(folder, required=["data/gta_vc.dat", "models/gta3.img"])

    def steam_installs(self):
        return []

    def check_tools(self):
        return MACOS.check_tools(self.runner)

    def tools_present(self):
        return MACOS.tools_present(self.runner)

    def request_tools_install(self):
        MACOS.request_tools_install(self.runner)

    def build(self, folder, start="validate", stop_after=None):
        self.builds.append((Path(folder), start))
        stages = BUILD_STAGES[BUILD_STAGES.index(start):] if start in BUILD_STAGES else BUILD_STAGES
        for stage in stages:
            self._emit(StageStarted(stage, stage))
            self._emit(LogLine(stage, f"working on {stage}"))
            self._emit(Progress(stage, 0.5, ""))
            if stage == self.cancel_stage:
                self.cancel_stage = None
                self._emit(StageFailed(stage, None, cancelled=True))
                return PipelineResult(False, stage, None, cancelled=True)
            if stage == self.fail_stage:
                error = CompileError("ninja: build stopped: subcommand failed.")
                self.fail_stage = None  # the next attempt succeeds
                self._emit(StageFailed(stage, error))
                return PipelineResult(False, stage, error)
            self._emit(StageFinished(stage))
        self.installed_app = self.tmp_path / "Applications" / "reVC.app"
        return PipelineResult(True)

    def cancel(self):
        self.cancelled = True

    def log_text(self):
        return "FAKE LOG CONTENTS\nline two\n"


@pytest.fixture
def game_folder(tmp_path):
    return make_tree(tmp_path / "Vice City", ["data/gta_vc.dat", "models/gta3.img"])


def _window(qtbot, engine):
    window = MainWindow(engine, tools_poll_ms=20)
    qtbot.addWidget(window)
    window.show()
    return window


def _go_to_tools(qtbot, window, game_folder):
    qtbot.mouseClick(window.welcome.start_button, Qt.LeftButton)
    assert window.current_page() is window.game_files
    window.game_files.choose_folder(game_folder)
    assert window.game_files.next_button.isEnabled()
    qtbot.mouseClick(window.game_files.next_button, Qt.LeftButton)
    assert window.current_page() is window.tools


def test_page_flow_from_welcome_to_done(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path)
    window = _window(qtbot, engine)
    assert window.current_page() is window.welcome
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)
    qtbot.mouseClick(window.tools.next_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.done, timeout=5000)
    assert engine.builds == [(game_folder, "fetch")]
    assert str(engine.installed_app) in window.done.location_label.text()
    assert window.build.overall.value() == window.build.overall.maximum()


def test_invalid_folder_keeps_next_disabled(qtbot, tmp_path):
    window = _window(qtbot, FakeEngine(tmp_path))
    qtbot.mouseClick(window.welcome.start_button, Qt.LeftButton)
    window.game_files.choose_folder(make_tree(tmp_path / "Documents", ["notes.txt"]))
    assert not window.game_files.next_button.isEnabled()
    assert "data" in window.game_files.result_label.text() and "models" in window.game_files.result_label.text()


def test_error_page_shows_the_message_and_copies_the_log(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path, fail_stage="compile")
    window = _window(qtbot, engine)
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)
    qtbot.mouseClick(window.tools.next_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.error, timeout=5000)
    assert "The build failed" in window.error.message_label.text()

    QApplication.clipboard().clear()
    qtbot.mouseClick(window.error.copy_button, Qt.LeftButton)
    assert QApplication.clipboard().text() == engine.log_text()

    qtbot.mouseClick(window.error.retry_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.done, timeout=5000)
    assert engine.builds[-1] == (game_folder, "compile")


def test_tools_page_never_runs_clang_while_xcode_select_fails(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path, xcode_select_ok=False)
    window = _window(qtbot, engine)
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.install_button.isVisible(), timeout=2000)
    assert not engine.ran_clang()

    qtbot.mouseClick(window.tools.install_button, Qt.LeftButton)
    assert ("/usr/bin/xcode-select", "--install") in engine.runner.commands()
    qtbot.waitUntil(lambda: engine.runner.commands().count(("/usr/bin/xcode-select", "-p")) >= 4, timeout=2000)
    assert not engine.ran_clang()
    assert not window.tools.next_button.isEnabled()

    engine.xcode_select_ok = True
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)
    assert engine.ran_clang()


def test_tools_page_shows_the_licence_hint_when_clang_fails(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path, clang_ok=False)
    window = _window(qtbot, engine)
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.check_again_button.isVisible(), timeout=2000)
    assert "Xcode" in window.tools.status_label.text()
    assert "licen" in window.tools.status_label.text().lower()
    assert not window.tools.next_button.isEnabled()

    engine.clang_ok = True
    qtbot.mouseClick(window.tools.check_again_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)


def test_a_cancelled_build_offers_to_continue_where_it_stopped(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path, cancel_stage="deps")
    window = _window(qtbot, engine)
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)
    qtbot.mouseClick(window.tools.next_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.error, timeout=5000)
    assert window.error.heading_label.text() == "Build cancelled"
    assert "Something went wrong" not in window.error.heading_label.text()
    qtbot.mouseClick(window.error.retry_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.done, timeout=5000)
    assert engine.builds[-1] == (game_folder, "deps")


def test_cancel_asks_the_engine_to_stop(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path)
    window = _window(qtbot, engine)
    window.build.cancel_button.setEnabled(True)
    qtbot.mouseClick(window.build.cancel_button, Qt.LeftButton)
    assert engine.cancelled


def test_brazilian_portuguese_translation_is_available(qtbot, tmp_path):
    app = QApplication.instance()
    translator = install_translator(app, QLocale(QLocale.Portuguese, QLocale.Brazil))
    try:
        assert translator is not None
        window = _window(qtbot, FakeEngine(tmp_path))
        assert window.welcome.start_button.text() == "Começar"
    finally:
        app.removeTranslator(translator)
    english = _window(qtbot, FakeEngine(tmp_path))
    assert english.welcome.start_button.text() == "Get started"


def test_an_engine_crash_still_ends_on_the_error_page(qtbot, tmp_path, game_folder):
    engine = FakeEngine(tmp_path)

    def crash(folder, start="validate", stop_after=None):
        raise RuntimeError("unexpected")

    engine.build = crash
    window = _window(qtbot, engine)
    _go_to_tools(qtbot, window, game_folder)
    qtbot.waitUntil(lambda: window.tools.next_button.isEnabled(), timeout=2000)
    qtbot.mouseClick(window.tools.next_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page() is window.error, timeout=5000)
    assert "Something went wrong" in window.error.message_label.text()
