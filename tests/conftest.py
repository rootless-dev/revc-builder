"""Shared test helpers.

Nothing here touches the network or runs a compiler. One test in test_compile.py reads
(never writes) the Builder's reVC checkout in ~/Library/Caches when it exists, and is
skipped otherwise.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from vcbuilder.events import Event
from vcbuilder.runner import CancelToken, CommandFailed, CommandResult


def make_tree(root: Path, files: list[str], content: bytes = b"x") -> Path:
    """Create every file in ``files`` (relative paths) under ``root``."""
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


@dataclass
class FakeCall:
    argv: tuple[str, ...]
    cwd: Path | None
    stage: str


@dataclass
class FakeRunner:
    """Records commands instead of running them.

    ``responder`` decides the result of each command. It receives the argv tuple and
    returns ``(returncode, output)``, or ``None`` for ``(0, "")``. It may also raise.
    """

    responder: Callable[[tuple[str, ...]], tuple[int, str] | None] | None = None
    calls: list[FakeCall] = field(default_factory=list)
    cancel: CancelToken = field(default_factory=CancelToken)

    def run(self, argv, *, stage: str = "", cwd=None, env=None, check: bool = True) -> CommandResult:
        argv = tuple(str(part) for part in argv)
        self.calls.append(FakeCall(argv, Path(cwd) if cwd else None, stage))
        outcome = self.responder(argv) if self.responder else None
        returncode, output = outcome if outcome is not None else (0, "")
        result = CommandResult(argv=argv, returncode=returncode, output=output)
        if check and returncode != 0:
            raise CommandFailed(result)
        return result

    def log(self, stage: str, text: str) -> None:
        pass

    def commands(self) -> list[tuple[str, ...]]:
        return [call.argv for call in self.calls]


@pytest.fixture
def events() -> list[Event]:
    return []


def git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin",
        },
    )
    return completed.stdout.strip()


def make_repo(path: Path, files: dict[str, str], message: str = "initial") -> str:
    """Create a git repository at ``path`` with ``files`` committed; return the commit."""
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=path)
    for relative, text in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git("add", "-A", cwd=path)
    git("commit", "-q", "-m", message, cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def commit_all(path: Path, message: str) -> str:
    git("add", "-A", cwd=path)
    git("commit", "-q", "--allow-empty", "-m", message, cwd=path)
    return git("rev-parse", "HEAD", cwd=path)
