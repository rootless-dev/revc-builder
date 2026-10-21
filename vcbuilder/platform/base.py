"""The platform seam: everything the build kit does differently per operating system.

The pipeline, source handling, game-file validation, dependency build orchestration, INI
editing, the event stream, the CLI and the GUI are platform-neutral and reach
platform-specific behaviour only through a ``Platform`` obtained from
``vcbuilder.platform.current()``. Only macOS is implemented (``macos.py``).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Callable

from vcbuilder.errors import ClangFailedError, ToolsError
from vcbuilder.paths import Locations
from vcbuilder.runner import CancelToken, CommandRunner

#: Seconds between checks while waiting for the toolchain to be installed.
POLL_INTERVAL = 5.0

#: ``copier(source, destination, clone)`` copies a directory tree; with ``clone`` it may
#: use a cheap copy-on-write clone and raises ``CopyFailed`` when that is not possible.
from vcbuilder.install import Copier  # noqa: E402  (re-exported)


class ToolsStatus(Enum):
    READY = "ready"
    MISSING = "missing"
    #: The tools are present but the compiler does not run (e.g. an unaccepted licence).
    CLANG_FAILED = "clang_failed"


class Platform(ABC):
    name: str
    #: The ``platform`` value of this platform's entries in ``sources.lock``.
    lock_platform: str

    # --- installed layout ---------------------------------------------------------------

    @abstractmethod
    def locations(self, home: Path) -> Locations:
        """Where the Builder keeps its data, cache and logs, and where reVC keeps its files."""

    @abstractmethod
    def app_destination(self, locations: Locations, override: Path | None = None) -> Path:
        """The folder the built app is installed into."""

    @abstractmethod
    def built_app(self, revc_build: Path) -> Path:
        """The app the reVC build produces inside its CMake build directory."""

    @abstractmethod
    def steam_search_roots(self, home: Path) -> list[tuple[Path, Path]]:
        """``(container, game)`` pairs: every directory in ``container`` is a bottle or
        prefix, and ``<bottle>/<game>`` is where a default Steam library keeps the game."""

    @abstractmethod
    def copier(self, runner: CommandRunner, stage: str) -> Copier:
        """The directory copy strategy for the game data and the app."""

    @abstractmethod
    def volume_name(self, path: Path) -> str:
        """A name for the volume holding ``path``, for the not-enough-space message, or ""
        for the startup disk."""

    # --- toolchain ----------------------------------------------------------------------------

    @abstractmethod
    def tools_present(self, runner: CommandRunner) -> bool:
        """A cheap check that never triggers an install prompt; safe to poll."""

    @abstractmethod
    def check_tools(self, runner: CommandRunner) -> ToolsStatus:
        """Full check; runs the compiler only after ``tools_present`` succeeds."""

    @abstractmethod
    def request_tools_install(self, runner: CommandRunner) -> None:
        """Ask the operating system to install the toolchain."""

    def ensure_tools(
        self,
        runner: CommandRunner,
        cancel: CancelToken,
        *,
        interval: float = POLL_INTERVAL,
        sleep: Callable[[float], None] = time.sleep,
        stage: str = "tools",
    ) -> None:
        """Pipeline stage 2: request the install when the tools are missing, poll until they
        appear, then require a working compiler."""
        if not self.tools_present(runner):
            runner.log(stage, "Build tools not found; asking the system to install them.")
            self.request_tools_install(runner)
            while True:
                cancel.raise_if_cancelled()
                sleep(interval)
                cancel.raise_if_cancelled()
                if self.tools_present(runner):
                    break
        status = self.check_tools(runner)
        if status is ToolsStatus.CLANG_FAILED:
            raise ClangFailedError("the compiler failed after the tools were found")
        if status is ToolsStatus.MISSING:
            raise ToolsError("the build tools are missing")

    @abstractmethod
    def host_architecture(self) -> str:
        """The architecture to build for, in the platform's CMake spelling."""

    @abstractmethod
    def build_environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Environment for CMake and the compilers."""

    # --- CMake and the results -------------------------------------------------------------

    @abstractmethod
    def shared_library_name(self, stem: str, soversion: str) -> str:
        """File name of a versioned shared library, e.g. ``libglfw.3.dylib``."""

    @abstractmethod
    def dependency_cmake_definitions(self, arch: str, dependency: str) -> dict[str, str]:
        """Platform-specific ``-D`` definitions for building ``dependency`` (stage 4): the
        ones every dependency gets, plus any for that dependency alone (e.g. audio backends)."""

    @abstractmethod
    def verify_dependency_library(self, library: Path, runner: CommandRunner, *, stage: str) -> None:
        """Raise ``CompileError`` unless ``library`` can be bundled as built (stage 4)."""

    @abstractmethod
    def revc_cmake_definitions(self, prefix: Path, arch: str) -> dict[str, str]:
        """Platform-specific ``-D`` definitions for the reVC build (stage 5)."""

    @abstractmethod
    def verify_app(self, app: Path, runner: CommandRunner, *, stage: str) -> None:
        """Stage 6: raise ``BundleError`` unless the built app is self-contained and valid."""

    # --- renderers (Phase 2 design, section 7) ----------------------------------------------

    @abstractmethod
    def static_library_name(self, stem: str) -> str:
        """File name of a static library, e.g. ``librwgpu.a``."""

    @abstractmethod
    def verify_renderer(self, app: Path, renderer: str, runner: CommandRunner, *, stage: str) -> None:
        """Stage 6: raise ``CompileError`` unless the app uses ``renderer``'s graphics API."""
