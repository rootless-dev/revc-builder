"""Restore, patch, configure and build reVC (spec section 8, stage 5).

Platform-neutral; the platform adds its CMake definitions and names the built app.
Verifying the result (stage 6) is ``Platform.verify_app``.
"""

from __future__ import annotations

from pathlib import Path

from vcbuilder.errors import CompileError
from vcbuilder.platform.base import Platform
from vcbuilder.runner import CommandFailed, CommandRunner
from vcbuilder.renderers import Overlay, apply_overlay
from vcbuilder.sources import GIT, git_environment


def configure_command(
    platform: Platform, *, cmake: Path, ninja: Path, source: Path, build: Path, prefix: Path, arch: str,
    extra: dict[str, str] | None = None,
) -> list[str]:
    """``extra``: further definitions, such as the renderer's (Phase 2 design, section 7.3)."""
    lib = prefix / "lib"
    definitions = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_MAKE_PROGRAM": str(ninja),
        "CMAKE_PREFIX_PATH": str(prefix),
        # Cached values make find_package/find_path/find_library use the private prefix.
        "OpenAL_DIR": str(lib / "cmake" / "OpenAL"),
        "glfw3_DIR": str(lib / "cmake" / "glfw3"),
        "mpg123_INCLUDE_DIR": str(prefix / "include"),
        "mpg123_LIBRARIES": str(lib / platform.shared_library_name("mpg123", "0")),
        **platform.revc_cmake_definitions(prefix, arch),
        **(extra or {}),
    }
    return [str(cmake), "-S", str(source), "-B", str(build), "-G", "Ninja",
            *(f"-D{name}={value}" for name, value in definitions.items())]


def _git(runner: CommandRunner, repo: Path, *args: str, stage: str) -> None:
    runner.run([GIT, "-C", repo, *args], stage=stage, env=git_environment())


def restore_and_patch(
    checkout: Path, revc_commit: str, librw_commit: str, patches: list[Path], runner: CommandRunner, *, stage: str,
    overlay: Overlay | None = None,
) -> None:
    """Reset reVC and vendor/librw to their pins, apply ``patches`` in file-name order, then
    the renderer's ``overlay`` (Phase 2 design, section 7.3).

    The reset makes a retry start from pristine sources, so a patch is never applied twice.
    ``git clean`` without ``-x`` and with a single ``-f`` removes files a patch or the
    overlay added but leaves the nested librw repository alone.
    """
    librw = checkout / "vendor" / "librw"
    try:
        _git(runner, checkout, "reset", "--quiet", "--hard", revc_commit, stage=stage)
        _git(runner, checkout, "clean", "--quiet", "-f", "-d", stage=stage)
        _git(runner, librw, "reset", "--quiet", "--hard", librw_commit, stage=stage)
        _git(runner, librw, "clean", "--quiet", "-f", "-d", stage=stage)
        for patch in sorted(patches, key=lambda path: path.name):
            runner.log(stage, f"Applying {patch.name}")
            _git(runner, checkout, "apply", "--whitespace=nowarn", str(patch), stage=stage)
    except CommandFailed as failure:
        raise CompileError(str(failure)) from failure
    if overlay is not None:
        apply_overlay(checkout, librw, overlay, runner, stage=stage)


def build_revc(
    platform: Platform, *, cmake: Path, ninja: Path, source: Path, build: Path, prefix: Path, arch: str, env: dict[str, str],
    runner: CommandRunner, stage: str, extra: dict[str, str] | None = None,
) -> Path:
    command = configure_command(platform, cmake=cmake, ninja=ninja, source=source, build=build, prefix=prefix, arch=arch,
                                extra=extra)
    try:
        runner.run(command, stage=stage, env=env)
        runner.run([cmake, "--build", build, "--config", "Release"], stage=stage, env=env)
    except CommandFailed as failure:
        raise CompileError(str(failure)) from failure
    app = platform.built_app(build)
    if not app.exists():
        raise CompileError(f"the build finished but {app} was not produced")
    return app
