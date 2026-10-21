"""The renderers reVC can be built with (Phase 2 design, section 7).

``gl3`` is librw's OpenGL 3 backend (Phase 1). ``wgpu`` is librw's WGPU platform, whose
rendering is the prebuilt rwgpu library pinned in ``sources.lock``. Each renderer has an
overlay in ``renderers/<name>``: files copied into reVC and its librw, and patches
applied on top of them. Platform-neutral; file names and checks that differ per
operating system come from the ``Platform``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from vcbuilder.errors import CompileError, RendererUnavailableError  # noqa: F401 (re-exported)
from vcbuilder.platform.base import Platform
from vcbuilder.resources import renderers_dir
from vcbuilder.runner import CommandFailed, CommandRunner
from vcbuilder.sources import GIT, ArchiveSource, Lock, git_environment


@dataclass(frozen=True)
class Renderer:
    name: str
    #: librw's LIBRW_PLATFORM.
    librw_platform: str
    #: Whether the build links the prebuilt rwgpu library.
    needs_rwgpu: bool


RENDERERS = {
    "gl3": Renderer("gl3", "GL3", needs_rwgpu=False),
    "wgpu": Renderer("wgpu", "WGPU", needs_rwgpu=True),
}

#: The renderer the GUI builds and the CLI uses without --renderer (design D5, section 10).
DEFAULT_RENDERER = "gl3"


def get(name: str) -> Renderer:
    try:
        return RENDERERS[name]
    except KeyError:
        raise ValueError(f"unknown renderer {name!r}; expected one of {sorted(RENDERERS)}") from None


# --- the prebuilt library ------------------------------------------------------------------


def archives_to_fetch(lock: Lock, renderer: Renderer, platform: str, *, override: Path | None) -> list[ArchiveSource]:
    """The archives stage 3 downloads for this build.

    The renderer library is left out when the development override is set; a placeholder
    entry that would be needed stops the build, since there is nothing to download.
    """
    plan = []
    for archive in lock.archives_for(renderer.name, platform):
        if archive.renderer is not None:
            if override is not None:
                continue
            if archive.placeholder:
                raise RendererUnavailableError(f"sources.{archive.name} is a placeholder")
        plan.append(archive)
    return plan


@dataclass(frozen=True)
class RwgpuLibrary:
    root: Path
    library: Path
    include_dir: Path
    #: System libraries the static library needs, as listed in lib/link-libs.txt.
    link_libs: list[str]


def rwgpu_library(root: Path, platform: Platform) -> RwgpuLibrary:
    """The library in an extracted archive or a development override directory."""
    library = root / "lib" / platform.static_library_name("rwgpu")
    header = root / "include" / "rwgpu.h"
    link_libs = root / "lib" / "link-libs.txt"
    missing = [str(p) for p in (library, header, link_libs) if not p.is_file()]
    if missing:
        raise CompileError(f"the rwgpu library is incomplete: missing {', '.join(missing)}")
    libs = [line.strip() for line in link_libs.read_text(encoding="utf-8").splitlines() if line.strip()]
    return RwgpuLibrary(root, library, header.parent, libs)


def cmake_definitions(renderer: Renderer, library: RwgpuLibrary | None) -> dict[str, str]:
    definitions = {"LIBRW_PLATFORM": renderer.librw_platform}
    if renderer.needs_rwgpu:
        if library is None:
            raise CompileError(f"the {renderer.name} renderer needs the rwgpu library")
        definitions["RWGPU_LIBRARY"] = str(library.library)
        definitions["RWGPU_INCLUDE_DIR"] = str(library.include_dir)
        definitions["RWGPU_LINK_LIBS"] = ";".join(library.link_libs)
    return definitions


# --- overlays ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Overlay:
    librw_files: Path | None
    librw_patches: list[Path]
    revc_files: Path | None
    revc_patches: list[Path]

    @staticmethod
    def at(directory: Path) -> "Overlay":
        def files(path: Path) -> Path | None:
            return path if path.is_dir() else None

        def patches(path: Path) -> list[Path]:
            return sorted(path.glob("*.patch"), key=lambda p: p.name) if path.is_dir() else []

        return Overlay(
            librw_files=files(directory / "librw" / "files"),
            librw_patches=patches(directory / "librw" / "patches"),
            revc_files=files(directory / "revc" / "files"),
            revc_patches=patches(directory / "revc" / "patches"),
        )


def overlay_for(renderer: Renderer) -> Overlay:
    return Overlay.at(renderers_dir() / renderer.name)


def _copy_tree(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def apply_overlay(checkout: Path, librw: Path, overlay: Overlay, runner: CommandRunner, *, stage: str) -> None:
    """Copies the overlay's files and applies its patches, librw first."""
    try:
        if overlay.librw_files:
            _copy_tree(overlay.librw_files, librw)
        for patch in overlay.librw_patches:
            runner.log(stage, f"Applying {patch.name} to librw")
            runner.run([GIT, "-C", librw, "apply", "--whitespace=nowarn", str(patch)], stage=stage, env=git_environment())
        if overlay.revc_files:
            _copy_tree(overlay.revc_files, checkout)
        for patch in overlay.revc_patches:
            runner.log(stage, f"Applying {patch.name}")
            runner.run([GIT, "-C", checkout, "apply", "--whitespace=nowarn", str(patch)], stage=stage, env=git_environment())
    except CommandFailed as failure:
        raise CompileError(str(failure)) from failure
