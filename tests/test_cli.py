from __future__ import annotations

from tests.conftest import make_tree
from vcbuilder.__main__ import main, render_event
from vcbuilder.errors import CompileError
from vcbuilder.events import LogLine, Progress, StageFailed, StageFinished, StageStarted


def test_cli_stops_at_validation_for_a_wrong_folder(tmp_path, capsys):
    folder = make_tree(tmp_path / "not-a-game", ["readme.txt"])
    code = main([str(folder), "--home", str(tmp_path / "home")])
    captured = capsys.readouterr()
    assert code == 1
    assert "Not a game folder" in captured.err
    logs = list((tmp_path / "home" / "Library" / "Logs" / "reVC Builder").glob("build-*.log"))
    assert len(logs) == 1


def test_cli_renders_events_as_text():
    assert render_event(StageStarted("deps", "Build dependencies")) == "==> Build dependencies"
    assert render_event(Progress("deps", 0.5, "glfw")) == "    50% glfw"
    assert render_event(LogLine("deps", "cc -c foo.c"), verbose=True) == "    cc -c foo.c"
    assert render_event(LogLine("deps", "cc -c foo.c"), verbose=False) is None
    assert render_event(StageFinished("deps")) is None
    failed = render_event(StageFailed("compile", CompileError("ninja: build stopped")))
    assert failed.startswith("ERROR: The build failed.")
    assert render_event(StageFailed("compile", None, cancelled=True)) == "Cancelled."
