"""The locations the Builder reads and writes (spec section 6.3).

The platform decides the five base folders (``Platform.locations``); everything below
them is laid out the same way on every platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Locations:
    home: Path
    #: The Builder's own data; the copied game data lives in ``game`` inside it.
    builder_data: Path
    #: reVC's settings and saves; reVC owns this folder.
    revc_user_files: Path
    cache: Path
    logs: Path

    @property
    def game_data(self) -> Path:
        return self.builder_data / "game"

    @property
    def revc_ini(self) -> Path:
        return self.revc_user_files / "reVC.ini"

    @property
    def downloads(self) -> Path:
        return self.cache / "downloads"

    @property
    def sources(self) -> Path:
        return self.cache / "src"

    @property
    def revc_checkout(self) -> Path:
        return self.sources / "reVC"

    @property
    def build(self) -> Path:
        return self.cache / "build"

    def revc_build_for(self, renderer: str) -> Path:
        """reVC's CMake build directory for ``renderer``; GL3 keeps Phase 1's ``reVC``."""
        return self.build / ("reVC" if renderer == "gl3" else f"reVC-{renderer}")

    @property
    def prefix(self) -> Path:
        return self.cache / "prefix"
