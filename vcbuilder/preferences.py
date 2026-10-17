"""What the Builder remembers between runs, kept in its own data directory."""

from __future__ import annotations

import json
from pathlib import Path

FILE_NAME = "preferences.json"


class Preferences:
    def __init__(self, builder_data: Path) -> None:
        self.path = Path(builder_data) / FILE_NAME

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def last_game_folder(self) -> Path | None:
        """The folder chosen last time, or None when there is none or it no longer exists."""
        value = self._read().get("last_game_folder")
        if not isinstance(value, str):
            return None
        folder = Path(value)
        return folder if folder.is_dir() else None

    def remember_game_folder(self, folder: Path) -> None:
        data = self._read()
        data["last_game_folder"] = str(Path(folder))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
