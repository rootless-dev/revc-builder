"""Build GLFW, OpenAL Soft and mpg123 into the private prefix (spec section 8, stage 4).

Platform-neutral orchestration; the platform supplies its CMake definitions, library
file names and the per-library check.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from vcbuilder.errors import CompileError
from vcbuilder.platform.base import Platform
from vcbuilder.resources import PACKAGE_DATA
from vcbuilder.runner import CommandFailed, CommandRunner


@dataclass(frozen=True)
class Dependency:
    name: str
    #: The library reVC bundles (spec F2) is ``platform.shared_library_name(stem, soversion)``,
    #: e.g. ``libglfw.3.dylib`` on macOS.
    stem: str
    soversion: str
    #: Directory inside the extracted archive that holds the top-level CMakeLists.txt.
    source_subdir: str = ""
    options: dict[str, str] = field(default_factory=dict)
    extra_definitions: dict[str, str] = field(default_factory=dict)


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        name="glfw",
        stem="glfw",
        soversion="3",
        options={
            "GLFW_BUILD_EXAMPLES": "OFF",
            "GLFW_BUILD_TESTS": "OFF",
            "GLFW_BUILD_DOCS": "OFF",
            "GLFW_INSTALL": "ON",
        },
    ),
    Dependency(
        name="openal-soft",
        stem="openal",
        soversion="1",
        options={
            "ALSOFT_UTILS": "OFF",
            "ALSOFT_EXAMPLES": "OFF",
            "ALSOFT_TESTS": "OFF",
            "ALSOFT_INSTALL_CONFIG": "OFF",
            "ALSOFT_INSTALL_HRTF_DATA": "OFF",
            "ALSOFT_INSTALL_AMBDEC_PRESETS": "OFF",
            "ALSOFT_INSTALL_EXAMPLES": "OFF",
            "ALSOFT_INSTALL_UTILS": "OFF",
            "ALSOFT_UPDATE_BUILD_VERSION": "OFF",
            # Audio backends are chosen by the platform (dependency_cmake_definitions).
        },
    ),
    Dependency(
        name="mpg123",
        stem="mpg123",
        soversion="0",
        source_subdir="ports/cmake",
        options={
            "BUILD_PROGRAMS": "OFF",
            "BUILD_LIBOUT123": "OFF",
        },
        extra_definitions={
            "CMAKE_PROJECT_mpg123_INCLUDE": str(PACKAGE_DATA / "cmake" / "mpg123-soversion.cmake"),
        },
    ),
)


def dependency_configure_command(
    dependency: Dependency,
    platform: Platform,
    *,
    cmake: Path,
    ninja: Path,
    source: Path,
    build: Path,
    prefix: Path,
    arch: str,
) -> list[str]:
    source_dir = source / dependency.source_subdir if dependency.source_subdir else source
    definitions = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_MAKE_PROGRAM": str(ninja),
        "CMAKE_INSTALL_PREFIX": str(prefix),
        "CMAKE_INSTALL_LIBDIR": "lib",
        "BUILD_SHARED_LIBS": "ON",
        **platform.dependency_cmake_definitions(arch, dependency.name),
        **dependency.options,
        **dependency.extra_definitions,
    }
    return [str(cmake), "-S", str(source_dir), "-B", str(build), "-G", "Ninja", "--fresh",
            *(f"-D{name}={value}" for name, value in definitions.items())]


def library_path(prefix: Path, dependency: Dependency, platform: Platform) -> Path:
    return prefix / "lib" / platform.shared_library_name(dependency.stem, dependency.soversion)


def verify_prefix(
    prefix: Path,
    platform: Platform,
    runner: CommandRunner,
    *,
    stage: str,
    only: tuple[Dependency, ...] = DEPENDENCIES,
) -> None:
    """Fail unless each library exists in ``prefix/lib`` and the platform accepts it."""
    for dependency in only:
        library = library_path(prefix, dependency, platform)
        if not library.is_file():
            raise CompileError(f"{library} was not produced by the {dependency.name} build")
        platform.verify_dependency_library(library, runner, stage=stage)


def _stamp(prefix: Path, dependency: Dependency, version: str, arch: str) -> Path:
    return prefix / ".stamps" / f"{dependency.name}-{version}-{arch}"


def build_dependency(
    dependency: Dependency,
    version: str,
    platform: Platform,
    *,
    source: Path,
    build_root: Path,
    prefix: Path,
    cmake: Path,
    ninja: Path,
    arch: str,
    env: dict[str, str],
    runner: CommandRunner,
    stage: str,
) -> None:
    stamp = _stamp(prefix, dependency, version, arch)
    if stamp.exists():
        try:
            verify_prefix(prefix, platform, runner, stage=stage, only=(dependency,))
            runner.log(stage, f"{dependency.name} {version} is already built; skipping.")
            return
        except CompileError:
            stamp.unlink()
    build = build_root / f"{dependency.name}-{version}-{arch}"
    command = dependency_configure_command(
        dependency, platform, cmake=cmake, ninja=ninja, source=source, build=build, prefix=prefix, arch=arch
    )
    try:
        runner.run(command, stage=stage, env=env)
        runner.run([cmake, "--build", build, "--config", "Release"], stage=stage, env=env)
        runner.run([cmake, "--install", build, "--config", "Release"], stage=stage, env=env)
    except CommandFailed as failure:
        raise CompileError(str(failure)) from failure
    verify_prefix(prefix, platform, runner, stage=stage, only=(dependency,))
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{dependency.name} {version} {arch}\n")


def reset_prefix(prefix: Path) -> None:
    shutil.rmtree(prefix, ignore_errors=True)
