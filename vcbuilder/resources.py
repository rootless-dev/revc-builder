"""Files the engine ships with: the source lock, the reVC patches and the required-file list.

In a wheel or the packaged app, ``sources.lock`` and ``patches/`` are copied into
``vcbuilder/data``. In a source checkout they live at the repository root.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def _locate(name: str) -> Path:
    for candidate in (PACKAGE_DATA / name, REPOSITORY_ROOT / name):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{name} is missing from both {PACKAGE_DATA} and {REPOSITORY_ROOT}")


def lock_path() -> Path:
    return _locate("sources.lock")


def patches_dir() -> Path:
    return _locate("patches")


def patch_files() -> list[Path]:
    """Patches applied on top of reVC, in file-name order (spec section 8, stage 5)."""
    return sorted(patches_dir().glob("*.patch"), key=lambda path: path.name)


def required_files_path() -> Path:
    return PACKAGE_DATA / "required_files.txt"
