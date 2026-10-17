"""Ordered build stages, progress events and cancellation (spec section 8)."""

from __future__ import annotations

import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from vcbuilder import compile as compile_stage
from vcbuilder import deps, install, sources
from vcbuilder.errors import BuildError, IncompleteGameError, InstallOverlapError, NotGameFolderError
from vcbuilder.events import Emit, Event, LogLine, Progress, StageFailed, StageFinished, StageStarted
from vcbuilder.gamefiles import ValidationResult, ValidationStatus, validate_game_folder
from vcbuilder.paths import Locations
from vcbuilder.platform.base import Platform
from vcbuilder.runner import CancelToken, Cancelled, CommandRunner
from vcbuilder.sources import Lock
from vcbuilder.toolchain import cmake_executable, ninja_executable

STAGE_IDS = ("validate", "tools", "fetch", "deps", "compile", "verify", "install")

STAGE_TITLES = {
    "validate": "Validate game files",
    "tools": "Check tools",
    "fetch": "Fetch sources",
    "deps": "Build dependencies",
    "compile": "Build reVC",
    "verify": "Verify the bundle",
    "install": "Install",
}


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    run: Callable[[Any], None]


@dataclass(frozen=True)
class PipelineResult:
    succeeded: bool
    failed_stage: str | None = None
    error: BuildError | None = None
    cancelled: bool = False


class Pipeline:
    def __init__(self, stages: Sequence[Stage], emit: Emit, cancel: CancelToken | None = None) -> None:
        self.stages = list(stages)
        self.emit = emit
        self.cancel = cancel or CancelToken()

    def run(self, context: Any, start: str | None = None, stop_after: str | None = None) -> PipelineResult:
        ids = [stage.id for stage in self.stages]
        for name in (start, stop_after):
            if name is not None and name not in ids:
                raise ValueError(f"unknown stage {name!r}; expected one of {ids}")
        first = ids.index(start) if start else 0
        last = ids.index(stop_after) if stop_after else len(ids) - 1
        if last < first:
            raise ValueError(f"stage {stop_after!r} comes before {start!r}")
        for stage in self.stages[first:last + 1]:
            if self.cancel.cancelled:
                return PipelineResult(False, stage.id, None, cancelled=True)
            self.emit(StageStarted(stage.id, stage.title))
            try:
                stage.run(context)
            except Cancelled:
                self.emit(StageFailed(stage.id, None, cancelled=True))
                return PipelineResult(False, stage.id, None, cancelled=True)
            except BuildError as error:
                self.emit(StageFailed(stage.id, error))
                return PipelineResult(False, stage.id, error)
            except Exception as unexpected:  # a bug, not a user problem: keep the traceback
                for line in traceback.format_exception(unexpected):
                    for text in line.rstrip("\n").splitlines():
                        self.emit(LogLine(stage.id, text))
                error = BuildError(f"{type(unexpected).__name__}: {unexpected}")
                self.emit(StageFailed(stage.id, error))
                return PipelineResult(False, stage.id, error)
            self.emit(StageFinished(stage.id))
        return PipelineResult(True)


# --- the real stages -----------------------------------------------------------------------------


@dataclass
class BuildContext:
    game_folder: Path
    platform: Platform
    locations: Locations
    lock: Lock
    patches: list[Path]
    runner: CommandRunner
    emit: Emit
    cancel: CancelToken
    arch: str = ""
    #: Where to install the app instead of the platform's default (CLI ``--applications``).
    app_destination: Path | None = None
    sleep: Callable[[float], None] = time.sleep
    validation: ValidationResult | None = None
    installed_app: Path | None = None
    game_data: Path | None = None

    def __post_init__(self) -> None:
        if not self.arch:
            self.arch = self.platform.host_architecture()

    @property
    def built_app(self) -> Path:
        return self.platform.built_app(self.locations.revc_build)

    def progress(self, stage: str, fraction: float | None, message: str = "") -> None:
        self.emit(Progress(stage, fraction, message))

    def log(self, stage: str, text: str) -> None:
        self.emit(LogLine(stage, text))


_NINJA_STEP = re.compile(r"^\[(\d+)/(\d+)\]")


def ninja_progress(emit: Emit) -> Emit:
    """Turn Ninja's ``[n/m]`` lines into ``Progress`` events after forwarding them."""

    def forward(event: Event) -> None:
        emit(event)
        if isinstance(event, LogLine) and event.stage in ("deps", "compile"):
            match = _NINJA_STEP.match(event.text)
            if match:
                done, total = int(match.group(1)), int(match.group(2))
                if total:
                    emit(Progress(event.stage, done / total, ""))

    return forward


def stage_validate(context: BuildContext) -> None:
    result = validate_game_folder(context.game_folder, builder_data=context.locations.builder_data)
    context.validation = result
    if result.status is ValidationStatus.VALID:
        context.log("validate", f"{context.game_folder} contains every required file.")
        return
    for missing in result.missing:
        context.log("validate", f"missing: {missing}")
    if result.status is ValidationStatus.BUILDER_FOLDER:
        raise InstallOverlapError(str(context.game_folder))
    if result.status is ValidationStatus.NOT_GAME_FOLDER:
        raise NotGameFolderError(str(context.game_folder))
    raise IncompleteGameError(
        f"{len(result.missing)} files missing from {context.game_folder}",
        count=len(result.missing),
        examples=", ".join(result.shown_missing),
        missing=result.shown_missing,
    )


def stage_tools(context: BuildContext) -> None:
    context.platform.ensure_tools(context.runner, context.cancel, sleep=context.sleep, stage="tools")


def _extracted_marker(locations: Locations, archive: sources.ArchiveSource) -> Path:
    return locations.sources / f".{archive.name}-{archive.version}.extracted"


def extracted_source(locations: Locations, archive: sources.ArchiveSource) -> Path | None:
    marker = _extracted_marker(locations, archive)
    if not marker.is_file():
        return None
    directory = locations.sources / marker.read_text().strip()
    return directory if directory.is_dir() else None


def stage_fetch(context: BuildContext) -> None:
    locations, runner = context.locations, context.runner
    steps = 1 + len(context.lock.archives)
    context.progress("fetch", 0.0, "reVC")
    sources.fetch_revc(context.lock.revc, context.lock.librw, locations.revc_checkout, runner, stage="fetch")
    for index, archive in enumerate(context.lock.archives, start=1):
        context.cancel.raise_if_cancelled()
        context.progress("fetch", index / steps, f"{archive.name} {archive.version}")
        downloaded = sources.fetch_archive(archive, locations.downloads, runner=runner, stage="fetch")
        if extracted_source(locations, archive) is None:
            root = sources.extract_archive(downloaded, locations.sources)
            _extracted_marker(locations, archive).write_text(root.name + "\n")
    context.progress("fetch", 1.0, "")


def stage_deps(context: BuildContext) -> None:
    env = context.platform.build_environment()
    total = len(deps.DEPENDENCIES)
    for index, dependency in enumerate(deps.DEPENDENCIES):
        context.cancel.raise_if_cancelled()
        archive = context.lock.archive(dependency.name)
        source = extracted_source(context.locations, archive)
        if source is None:
            raise BuildError(f"{dependency.name} has not been fetched; run the fetch stage first")
        context.progress("deps", index / total, f"{dependency.name} {archive.version}")
        deps.build_dependency(
            dependency,
            archive.version,
            context.platform,
            source=source,
            build_root=context.locations.build,
            prefix=context.locations.prefix,
            cmake=cmake_executable(),
            ninja=ninja_executable(),
            arch=context.arch,
            env=env,
            runner=context.runner,
            stage="deps",
        )
    deps.verify_prefix(context.locations.prefix, context.platform, context.runner, stage="deps")


def stage_compile(context: BuildContext) -> None:
    locations = context.locations
    compile_stage.restore_and_patch(
        locations.revc_checkout,
        context.lock.revc.commit,
        context.lock.librw.commit,
        context.patches,
        context.runner,
        stage="compile",
    )
    compile_stage.build_revc(
        context.platform,
        cmake=cmake_executable(),
        ninja=ninja_executable(),
        source=locations.revc_checkout,
        build=locations.revc_build,
        prefix=locations.prefix,
        arch=context.arch,
        env=context.platform.build_environment(),
        runner=context.runner,
        stage="compile",
    )


def stage_verify(context: BuildContext) -> None:
    context.platform.verify_app(context.built_app, context.runner, stage="verify")


def stage_install(context: BuildContext) -> None:
    locations, runner = context.locations, context.runner
    copier = context.platform.copier(runner, "install")

    # Game data first: a disk-space or copy failure then stops before anything is replaced.
    context.progress("install", 0.0, "game data")
    context.game_data = install.copy_game_data(
        context.game_folder,
        locations.builder_data,
        copier=copier,
        volume_name=context.platform.volume_name,
        log=lambda text: context.log("install", text),
    )
    destination = context.platform.app_destination(locations, context.app_destination)
    context.progress("install", 0.8, context.built_app.name)
    context.installed_app = install.install_app(context.built_app, destination, copier=copier)
    context.log("install", f"Installed {context.installed_app}")
    context.progress("install", 0.9, "reVC.ini")
    install.set_game_path(locations.revc_ini, context.game_data)
    context.log("install", f"GamePath={context.game_data} written to {locations.revc_ini}")
    context.progress("install", 1.0, "")


_STAGE_FUNCTIONS = {
    "validate": stage_validate,
    "tools": stage_tools,
    "fetch": stage_fetch,
    "deps": stage_deps,
    "compile": stage_compile,
    "verify": stage_verify,
    "install": stage_install,
}


def default_stages() -> list[Stage]:
    return [Stage(stage_id, STAGE_TITLES[stage_id], _STAGE_FUNCTIONS[stage_id]) for stage_id in STAGE_IDS]
