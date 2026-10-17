"""The engine facade used by the CLI and the GUI.

A session owns one build log and offers every operation a front end needs, so neither
front end runs a command or touches the file system for build work itself (spec section 4).
"""

from __future__ import annotations

import threading
from pathlib import Path

from vcbuilder.errors import BuildError, LockError
from vcbuilder.events import Emit, Event, StageFailed
from vcbuilder.gamefiles import ValidationResult, detect_steam_installs, validate_game_folder
from vcbuilder import platform as platforms
from vcbuilder.platform.base import Platform, ToolsStatus
from vcbuilder.pipeline import BuildContext, Pipeline, PipelineResult, default_stages, ninja_progress
from vcbuilder.resources import lock_path, patch_files
from vcbuilder.runner import BuildLog, CancelToken, CommandRunner
from vcbuilder.sources import load_lock


class BuildSession:
    def __init__(
        self,
        *,
        home: Path | None = None,
        emit: Emit | None = None,
        app_destination: Path | None = None,
        platform: Platform | None = None,
    ) -> None:
        """``platform`` defaults to ``vcbuilder.platform.current()``, which raises
        ``UnsupportedPlatformError`` on an unsupported operating system."""
        self.platform = platform or platforms.current()
        self.locations = self.platform.locations(home or Path.home())
        self.app_destination = app_destination
        self.log = BuildLog.create(self.locations.logs)
        self._listeners: list[Emit] = [self.log.write]
        if emit is not None:
            self._listeners.append(emit)
        self._lock = threading.Lock()
        self._cancel = CancelToken()
        self.last_result: PipelineResult | None = None
        self.installed_app: Path | None = None
        self.game_data: Path | None = None

    # events -------------------------------------------------------------------------------

    def subscribe(self, listener: Emit) -> None:
        self._listeners.append(listener)

    def _emit(self, event: Event) -> None:
        for listener in list(self._listeners):
            listener(event)

    @property
    def log_path(self) -> Path:
        return self.log.path

    def log_text(self) -> str:
        return self.log.read_text()

    def _runner(self, cancel: CancelToken | None = None) -> CommandRunner:
        return CommandRunner(emit=ninja_progress(self._emit), cancel=cancel or CancelToken())

    # stage 1 and 2, step by step (GUI pages 2 and 3) ---------------------------------------

    def validate(self, folder: Path) -> ValidationResult:
        result = validate_game_folder(folder, builder_data=self.locations.builder_data)
        self.log.note(f"Validated {folder}: {result.status.value}, {len(result.missing)} missing")
        for missing in result.missing:
            self.log.note(f"  missing: {missing}")
        return result

    def steam_installs(self) -> list[Path]:
        return detect_steam_installs(self.platform.steam_search_roots(self.locations.home))

    def check_tools(self) -> ToolsStatus:
        return self.platform.check_tools(self._runner())

    def tools_present(self) -> bool:
        """The cheap check only: safe to poll, never opens an install prompt."""
        return self.platform.tools_present(self._runner())

    def request_tools_install(self) -> None:
        self.platform.request_tools_install(self._runner())

    # the pipeline ---------------------------------------------------------------------------

    def cancel(self) -> None:
        with self._lock:
            self._cancel.cancel()

    def build(self, game_folder: Path, start: str = "validate", stop_after: str | None = None) -> PipelineResult:
        """Run the pipeline from ``start`` (the GUI uses "fetch"; "Try again" the failed stage)."""
        with self._lock:
            self._cancel = CancelToken()
            cancel = self._cancel
        runner = self._runner(cancel)
        try:
            lock = load_lock(lock_path())
            patches = patch_files()
        except (BuildError, OSError, ValueError) as problem:
            error = problem if isinstance(problem, BuildError) else LockError(f"{type(problem).__name__}: {problem}")
            self._emit(StageFailed(start, error))
            self.last_result = PipelineResult(False, start, error)
            return self.last_result
        context = BuildContext(
            game_folder=Path(game_folder),
            platform=self.platform,
            locations=self.locations,
            lock=lock,
            patches=patches,
            runner=runner,
            emit=self._emit,
            cancel=cancel,
            app_destination=self.app_destination,
        )
        result = Pipeline(default_stages(), emit=self._emit, cancel=cancel).run(context, start=start, stop_after=stop_after)
        self.last_result = result
        self.installed_app = context.installed_app
        self.game_data = context.game_data
        return result

    def close(self) -> None:
        self.log.close()
