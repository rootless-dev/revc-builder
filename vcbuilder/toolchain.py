"""Locate the CMake and Ninja the Builder ships (the pinned PyPI wheels, spec section 5).

Everything about the system compiler is platform-specific and lives in
``vcbuilder.platform``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _frozen_tools_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "tools" if base else None


def cmake_executable() -> Path:
    override = os.environ.get("VCBUILDER_CMAKE")
    if override:
        return Path(override)
    frozen = _frozen_tools_dir()
    if frozen and (frozen / "cmake" / "bin" / "cmake").is_file():
        return frozen / "cmake" / "bin" / "cmake"
    import cmake

    return Path(cmake.CMAKE_BIN_DIR) / "cmake"


def ninja_executable() -> Path:
    override = os.environ.get("VCBUILDER_NINJA")
    if override:
        return Path(override)
    frozen = _frozen_tools_dir()
    if frozen and (frozen / "ninja" / "ninja").is_file():
        return frozen / "ninja" / "ninja"
    import ninja

    return Path(ninja.BIN_DIR) / "ninja"


def tool_directories() -> list[str]:
    """The directories of the bundled CMake and Ninja, for the front of ``PATH``."""
    directories: list[str] = []
    for tool in (cmake_executable(), ninja_executable()):
        directory = str(tool.parent)
        if directory not in directories:
            directories.append(directory)
    return directories
