"""Install the app, copy the game data and point reVC at it (spec sections 6.3, 6.4, stage 7).

Platform-neutral: the copy strategy (``copier``) and volume naming come from the platform.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from vcbuilder.errors import DiskSpaceError, InstallError, InstallOverlapError

#: A normal copy needs the size of the source plus 10 % free (spec section 6.3, step 3).
FREE_SPACE_MARGIN_PERCENT = 110

Copier = Callable[[Path, Path, bool], None]
FreeSpace = Callable[[Path], int]


class CopyFailed(Exception):
    pass


# --- reVC.ini ---------------------------------------------------------------------------------

_SECTION = re.compile(r"^\s*\[\s*(?P<name>[^\]]*?)\s*\]\s*$")
#: reVC's mINI is case-sensitive for keys too, so only ``GamePath`` is the key reVC reads.
_GAME_PATH = re.compile(r"^\s*GamePath\s*=")


def _split_line_ending(line: str) -> tuple[str, str]:
    for ending in ("\r\n", "\n", "\r"):
        if line.endswith(ending):
            return line[: -len(ending)], ending
    return line, ""


def edit_game_path(text: str, game_path: str) -> str:
    """Set ``[General] GamePath`` in INI ``text``, keeping every other line byte for byte."""
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    new_line = f"GamePath={game_path}"

    section = None
    general_end = None  # index after the last non-blank line of [General]
    replaced = False
    for index, line in enumerate(lines):
        body, ending = _split_line_ending(line)
        match = _SECTION.match(body)
        if match:
            # reVC's mINI is case-sensitive for section names (spec section 6.4).
            section = match.group("name")
            if section == "General" and general_end is None:
                general_end = index + 1
            continue
        if section == "General":
            if _GAME_PATH.match(body):
                # mINI keeps the last value of a repeated key, so only one GamePath line
                # may remain: the first is rewritten, later ones are dropped.
                lines[index] = "" if replaced else new_line + (ending or newline)
                replaced = True
                continue
            if body.strip():
                general_end = index + 1
    if replaced:
        return "".join(lines)

    if general_end is not None:
        before = lines[:general_end]
        if before and not _split_line_ending(before[-1])[1]:
            before[-1] += newline
        return "".join(before + [new_line + newline] + lines[general_end:])

    prefix = text
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += newline
    if prefix and prefix.strip():
        prefix += newline
    return f"{prefix}[General]{newline}{new_line}{newline}"


def set_game_path(ini_path: Path, game_path: Path) -> None:
    """Write ``GamePath`` into reVC's ini file, creating the file and its folder if needed."""
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    original = ini_path.read_bytes().decode("utf-8", errors="surrogateescape") if ini_path.exists() else ""
    edited = edit_game_path(original, str(game_path))
    temporary = ini_path.with_name(ini_path.name + ".tmp")
    temporary.write_bytes(edited.encode("utf-8", errors="surrogateescape"))
    if ini_path.exists():
        shutil.copymode(ini_path, temporary)
    os.replace(temporary, ini_path)


# --- game data copy ---------------------------------------------------------------------------


def available_space(path: Path) -> int:
    existing = path
    while not existing.exists():
        existing = existing.parent
    return shutil.disk_usage(existing).free


def folder_size(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _overlaps(source: Path, data_dir: Path) -> bool:
    return source == data_dir or source.is_relative_to(data_dir) or data_dir.is_relative_to(source)


def overlaps_builder_data(source: Path, data_dir: Path) -> bool:
    """True when ``source`` cannot be copied into ``data_dir`` (spec section 6.3, step 1):
    it overlaps the Builder's data directory and is not the ``game`` folder itself."""
    source = Path(os.path.realpath(source))
    data_dir = Path(os.path.realpath(data_dir))
    return source != data_dir / "game" and _overlaps(source, data_dir)


def copy_game_data(
    source: Path,
    data_dir: Path,
    *,
    copier: Copier,
    free_space: FreeSpace = available_space,
    volume_name: Callable[[Path], str] = str,
    log: Callable[[str], None] = lambda text: None,
) -> Path:
    """Copy ``source`` to ``data_dir/game`` through a staging directory (spec section 6.3)."""
    source = Path(os.path.realpath(source))
    data_dir = Path(os.path.realpath(data_dir))
    game = data_dir / "game"
    staging = data_dir / "game.new"
    previous = data_dir / "game.old"

    if source == game:
        log("The game data is already in place; nothing to copy.")
        return game
    if _overlaps(source, data_dir):
        raise InstallOverlapError(f"{source} overlaps {data_dir}")

    data_dir.mkdir(parents=True, exist_ok=True)
    for leftover in (staging, previous):
        if leftover.exists():
            log(f"Removing {leftover.name} left by an earlier run.")
            shutil.rmtree(leftover)

    try:
        try:
            copier(source, staging, True)
        except CopyFailed as clone_failure:
            log(f"Cloning failed ({clone_failure}); copying normally instead.")
            shutil.rmtree(staging, ignore_errors=True)
            needed = -(-folder_size(source) * FREE_SPACE_MARGIN_PERCENT // 100)
            free = free_space(data_dir)
            if free < needed:
                volume = volume_name(data_dir)
                raise DiskSpaceError(
                    f"{needed} bytes needed, {free} free",
                    needed_gb=f"{needed / 1e9:.1f}",
                    needed_bytes=needed,
                    # An empty name means the startup disk; front ends word that themselves.
                    volume=volume or "the startup disk",
                    startup_disk=not volume,
                )
            try:
                copier(source, staging, False)
            except CopyFailed as copy_failure:
                raise InstallError(str(copy_failure)) from copy_failure
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if game.exists():
        game.rename(previous)
    staging.rename(game)
    shutil.rmtree(previous, ignore_errors=True)
    return game


# --- application ------------------------------------------------------------------------------


def install_app(built_app: Path, destination_dir: Path, *, copier: Copier | None = None) -> Path:
    """Copy ``built_app`` into ``destination_dir``, replacing an earlier install only on success."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / built_app.name
    staging = destination_dir / f".{built_app.name}.new"
    previous = destination_dir / f".{built_app.name}.old"
    for leftover in (staging, previous):
        if leftover.exists():
            shutil.rmtree(leftover)
    try:
        if copier is None:
            shutil.copytree(built_app, staging, symlinks=True)
        else:
            try:
                copier(built_app, staging, True)  # clone first, as for the game data
            except CopyFailed:
                shutil.rmtree(staging, ignore_errors=True)
                copier(built_app, staging, False)
    except BaseException as failure:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(failure, (OSError, CopyFailed)):
            raise InstallError(str(failure)) from failure
        raise
    if target.exists():
        target.rename(previous)
    staging.rename(target)
    shutil.rmtree(previous, ignore_errors=True)
    return target
