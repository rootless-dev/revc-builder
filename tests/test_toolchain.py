from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FakeRunner
from vcbuilder.errors import ToolsError
from vcbuilder.runner import CancelToken, Cancelled, CommandRunner
from vcbuilder.platform.base import ToolsStatus
from vcbuilder.platform.macos import MacOSPlatform
from vcbuilder.toolchain import cmake_executable, ninja_executable

MACOS = MacOSPlatform()


def check_command_line_tools(runner):
    return MACOS.check_tools(runner)


def ensure_command_line_tools(runner, cancel, **kwargs):
    MACOS.ensure_tools(runner, cancel, **kwargs)


def build_environment():
    return MACOS.build_environment()


def host_architecture():
    return MACOS.host_architecture()


def _responder(xcode_select_ok: bool, clang_ok: bool = True):
    def respond(argv):
        if argv[:2] == ("/usr/bin/xcode-select", "-p"):
            return (0, "/Library/Developer/CommandLineTools\n") if xcode_select_ok else (2, "error: unable to get active developer directory")
        if argv[0] == "/usr/bin/clang":
            return (0, "Apple clang version 17") if clang_ok else (69, "You have not agreed to the Xcode license agreements.")
        return 0, ""

    return respond


def _ran_clang(runner: FakeRunner) -> bool:
    return any(call[0] == "/usr/bin/clang" for call in runner.commands())


def test_tools_ready():
    runner = FakeRunner(responder=_responder(True))
    assert check_command_line_tools(runner) is ToolsStatus.READY
    assert runner.commands() == [("/usr/bin/xcode-select", "-p"), ("/usr/bin/clang", "--version")]


def test_clang_is_never_run_while_xcode_select_fails():
    runner = FakeRunner(responder=_responder(False))
    assert check_command_line_tools(runner) is ToolsStatus.MISSING
    assert not _ran_clang(runner)


def test_clang_failure_after_xcode_select_is_reported_separately():
    runner = FakeRunner(responder=_responder(True, clang_ok=False))
    assert check_command_line_tools(runner) is ToolsStatus.CLANG_FAILED


def test_ensure_requests_install_and_polls_until_the_tools_appear():
    state = {"polls": 0}
    base_missing = _responder(False)
    base_ready = _responder(True)

    def respond(argv):
        if argv[:2] == ("/usr/bin/xcode-select", "-p"):
            state["polls"] += 1
            return (base_ready if state["polls"] >= 3 else base_missing)(argv)
        return base_ready(argv)

    runner = FakeRunner(responder=respond)
    sleeps = []
    ensure_command_line_tools(runner, CancelToken(), interval=5.0, sleep=sleeps.append)
    commands = runner.commands()
    assert ("/usr/bin/xcode-select", "--install") in commands
    clang_index = commands.index(("/usr/bin/clang", "--version"))
    assert clang_index == len(commands) - 1
    assert sleeps == [5.0, 5.0]


def test_ensure_reports_the_licence_hint_when_clang_fails():
    runner = FakeRunner(responder=_responder(True, clang_ok=False))
    with pytest.raises(ToolsError) as raised:
        ensure_command_line_tools(runner, CancelToken(), sleep=lambda s: None)
    assert raised.value.code == "clang_failed"


def test_ensure_can_be_cancelled_while_waiting():
    token = CancelToken()
    runner = FakeRunner(responder=_responder(False))

    def sleep(seconds):
        token.cancel()

    with pytest.raises(Cancelled):
        ensure_command_line_tools(runner, token, sleep=sleep)
    assert not _ran_clang(runner)


def test_bundled_cmake_and_ninja_are_found_and_new_enough():
    cmake = cmake_executable()
    ninja = ninja_executable()
    assert cmake.is_file() and ninja.is_file()
    runner = CommandRunner(emit=lambda event: None)
    version = runner.run([cmake, "--version"], stage="tools").output.split()[2]
    major, minor = (int(part) for part in version.split(".")[:2])
    assert (major, minor) >= (3, 24)  # --fresh (deps.py) needs 3.24
    assert "/opt/homebrew" not in str(cmake)


def test_build_environment_hides_package_managers(monkeypatch):
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    monkeypatch.setenv("PKG_CONFIG_PATH", "/opt/homebrew/lib/pkgconfig")
    monkeypatch.setenv("HOMEBREW_PREFIX", "/opt/homebrew")
    monkeypatch.setenv("CMAKE_PREFIX_PATH", "/opt/homebrew")
    env = build_environment()
    assert "/opt/homebrew" not in env["PATH"] and "/usr/local" not in env["PATH"]
    for name in ("PKG_CONFIG_PATH", "HOMEBREW_PREFIX", "CMAKE_PREFIX_PATH"):
        assert name not in env
    assert Path(env["PATH"].split(":")[0]) == cmake_executable().parent


def test_host_architecture_is_a_cmake_name():
    assert host_architecture() in {"arm64", "x86_64"}
