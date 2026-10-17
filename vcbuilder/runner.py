"""Subprocess execution with streamed output, cancellation and a persistent build log."""

from __future__ import annotations

import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from vcbuilder.events import Emit, Event, LogLine, Progress, StageFailed, StageFinished, StageStarted


class Cancelled(Exception):
    """Raised when the user cancels; it is not an error and has no message."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    def wait(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; return True early if cancelled."""
        return self._event.wait(seconds)


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    output: str


class CommandFailed(Exception):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        tail = "\n".join(result.output.splitlines()[-30:])
        super().__init__(f"{shlex.join(result.argv)} exited with {result.returncode}\n{tail}")


class CommandRunner:
    """Runs commands, forwarding each output line as a ``LogLine`` event.

    Every child runs in its own process group so that cancelling kills the whole tree
    (CMake and Ninja spawn compilers).
    """

    def __init__(self, emit: Emit, cancel: CancelToken | None = None, poll_interval: float = 0.1) -> None:
        self.emit = emit
        self.cancel = cancel or CancelToken()
        self.poll_interval = poll_interval

    def log(self, stage: str, text: str) -> None:
        self.emit(LogLine(stage, text))

    def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        stage: str = "",
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> CommandResult:
        self.cancel.raise_if_cancelled()
        args = tuple(str(part) for part in argv)
        self.emit(LogLine(stage, "$ " + shlex.join(args)))
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        lines: queue.Queue[bytes | None] = queue.Queue()

        def pump() -> None:
            assert process.stdout is not None
            for raw in iter(process.stdout.readline, b""):
                lines.put(raw)
            lines.put(None)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        collected: list[str] = []
        finished_reading = False
        try:
            while not finished_reading:
                if self.cancel.cancelled:
                    _kill_group(process)
                    raise Cancelled()
                try:
                    raw = lines.get(timeout=self.poll_interval)
                except queue.Empty:
                    continue
                if raw is None:
                    finished_reading = True
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                collected.append(text)
                self.emit(LogLine(stage, text))
            while process.poll() is None:
                if self.cancel.cancelled:
                    _kill_group(process)
                    raise Cancelled()
                time.sleep(self.poll_interval)
        finally:
            if process.poll() is None:
                _kill_group(process)
            reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()
        result = CommandResult(args, process.returncode, "\n".join(collected))
        if check and result.returncode != 0:
            self.emit(LogLine(stage, f"(exit status {result.returncode})"))
            raise CommandFailed(result)
        return result


def _kill_group(process: subprocess.Popen) -> None:
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    for sig, grace in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


class BuildLog:
    """Writes every event to ``build-<timestamp>.log`` (spec section 8, Errors)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._file = path.open("a", encoding="utf-8")

    @classmethod
    def create(cls, directory: Path) -> "BuildLog":
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"build-{stamp}.log"
        counter = 1
        while path.exists():
            counter += 1
            path = directory / f"build-{stamp}-{counter}.log"
        return cls(path)

    def write(self, event: Event) -> None:
        line = format_log_event(event)
        if line is None:
            return
        with self._lock:
            if self._file.closed:
                return
            self._file.write(line + "\n")
            self._file.flush()

    def note(self, text: str) -> None:
        self.write(LogLine("builder", text))

    def read_text(self) -> str:
        with self._lock:
            if not self._file.closed:
                self._file.flush()
        return self.path.read_text(encoding="utf-8", errors="replace")

    def close(self) -> None:
        with self._lock:
            self._file.close()


def format_log_event(event: Event) -> str | None:
    if isinstance(event, LogLine):
        return f"[{event.stage}] {event.text}"
    if isinstance(event, StageStarted):
        return f"=== [{event.stage}] {event.title} ({datetime.now().isoformat(timespec='seconds')})"
    if isinstance(event, StageFinished):
        return f"=== [{event.stage}] finished"
    if isinstance(event, StageFailed):
        if event.cancelled:
            return f"=== [{event.stage}] cancelled by the user"
        error = event.error
        detail = f"\n{error.detail}" if error is not None and error.detail else ""
        message = error.user_message if error is not None else "failed"
        return f"=== [{event.stage}] FAILED ({getattr(error, 'code', '?')}): {message}{detail}"
    if isinstance(event, Progress):
        if event.fraction is None:
            return f"[{event.stage}] {event.message}" if event.message else None
        return f"[{event.stage}] {event.fraction:.0%} {event.message}".rstrip()
    return None
