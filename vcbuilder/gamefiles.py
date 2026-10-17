"""Validate a game folder and detect Steam installs (spec section 6). Platform-neutral."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from vcbuilder.install import overlaps_builder_data
from vcbuilder.resources import required_files_path

#: The two files reVC itself checks to accept a folder as the game root (spec F5).
MARKER_FILES = ("data/gta_vc.dat", "models/gta3.img")

#: How many missing files the user sees; the full list goes to the log.
SHOWN_MISSING = 10

class ValidationStatus(Enum):
    VALID = "valid"
    NOT_GAME_FOLDER = "not_game_folder"
    INCOMPLETE = "incomplete"
    #: The folder overlaps the Builder's own data directory (spec section 6.3, step 1).
    BUILDER_FOLDER = "builder_folder"


@dataclass(frozen=True)
class ValidationResult:
    folder: Path
    status: ValidationStatus
    missing: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.status is ValidationStatus.VALID

    @property
    def shown_missing(self) -> tuple[str, ...]:
        return self.missing[:SHOWN_MISSING]


def load_required_files(path: Path | None = None) -> list[str]:
    """Read ``required_files.txt``: one relative path per line, ``#`` starts a comment."""
    text = (path or required_files_path()).read_text(encoding="utf-8")
    entries = []
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


class _DirectoryIndex:
    """Caches lower-cased directory listings so a long file list stays cheap to check."""

    def __init__(self) -> None:
        self._listings: dict[Path, dict[str, str]] = {}

    def entries(self, directory: Path) -> dict[str, str]:
        listing = self._listings.get(directory)
        if listing is None:
            listing = {}
            try:
                for name in sorted(os.listdir(directory)):
                    listing.setdefault(name.lower(), name)
            except OSError:
                pass
            self._listings[directory] = listing
        return listing

    def resolve(self, root: Path, relative: str) -> Path | None:
        current = root
        for part in Path(relative).parts:
            actual = self.entries(current).get(part.lower())
            if actual is None:
                return None
            current = current / actual
        return current


def resolve_case_insensitive(root: Path, relative: str) -> Path | None:
    """Return the real path of ``relative`` under ``root``, matching names case-insensitively."""
    return _DirectoryIndex().resolve(root, relative)


def validate_game_folder(
    folder: Path, required: list[str] | None = None, builder_data: Path | None = None
) -> ValidationResult:
    """``builder_data``, when given, is the Builder's data directory: a folder overlapping it
    (other than its ``game`` folder) is refused up front, since stage 7 could not copy it."""
    folder = Path(folder).expanduser()
    if builder_data is not None and overlaps_builder_data(folder, builder_data):
        return ValidationResult(folder, ValidationStatus.BUILDER_FOLDER, ())
    required = required if required is not None else load_required_files()
    index = _DirectoryIndex()

    def present(relative: str) -> bool:
        resolved = index.resolve(folder, relative)
        return resolved is not None and resolved.is_file()

    missing = tuple(relative for relative in required if not present(relative))
    if not missing:
        status = ValidationStatus.VALID
    elif not any(present(marker) for marker in MARKER_FILES):
        status = ValidationStatus.NOT_GAME_FOLDER
    else:
        status = ValidationStatus.INCOMPLETE
    return ValidationResult(folder, status, missing)


def detect_steam_installs(search_roots: list[tuple[Path, Path]]) -> list[Path]:
    """List game folders in default Steam libraries.

    ``search_roots`` comes from ``Platform.steam_search_roots``: for each
    ``(container, game)`` pair, every entry of ``container`` is a bottle and
    ``<bottle>/<game>`` is checked, in name order.
    """
    found = []
    for container, game in search_roots:
        try:
            names = sorted(os.listdir(container))
        except OSError:
            continue
        for name in names:
            candidate = container / name / game
            if candidate.is_dir():
                found.append(candidate)
    return found
