from __future__ import annotations

import threading
import time

import pytest

from vcbuilder.events import LogLine
from vcbuilder.runner import BuildLog, CancelToken, Cancelled, CommandFailed, CommandRunner


def test_runner_streams_output_as_log_lines(events):
    runner = CommandRunner(emit=events.append)
    result = runner.run(["/bin/sh", "-c", "echo one; echo two >&2"], stage="fetch")
    assert result.returncode == 0
    texts = [e.text for e in events if isinstance(e, LogLine)]
    assert texts[0].startswith("$ /bin/sh -c")
    assert "one" in texts and "two" in texts
    assert all(e.stage == "fetch" for e in events)
    assert result.output.splitlines() == ["one", "two"] or set(result.output.splitlines()) == {"one", "two"}


def test_runner_raises_on_failure_when_checking(events):
    runner = CommandRunner(emit=events.append)
    with pytest.raises(CommandFailed) as raised:
        runner.run(["/bin/sh", "-c", "echo bad; exit 3"], stage="deps")
    assert raised.value.result.returncode == 3
    assert runner.run(["/bin/sh", "-c", "exit 4"], stage="deps", check=False).returncode == 4


def test_runner_kills_the_child_on_cancel(tmp_path):
    token = CancelToken()
    marker = tmp_path / "survived"
    runner = CommandRunner(emit=lambda e: None, cancel=token)
    threading.Timer(0.3, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        runner.run(["/bin/sh", "-c", f"sleep 5; touch '{marker}'"], stage="compile")
    assert time.monotonic() - started < 3
    time.sleep(0.2)
    assert not marker.exists()


def test_runner_refuses_to_start_after_cancel():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        CommandRunner(emit=lambda e: None, cancel=token).run(["/usr/bin/true"], stage="x")


def test_build_log_writes_every_event(tmp_path):
    log = BuildLog.create(tmp_path / "Logs")
    assert log.path.parent == tmp_path / "Logs"
    assert log.path.name.startswith("build-") and log.path.suffix == ".log"
    runner = CommandRunner(emit=log.write)
    runner.run(["/bin/echo", "hello from a subprocess"], stage="deps")
    log.close()
    text = log.path.read_text()
    assert "hello from a subprocess" in text
    assert "[deps]" in text
