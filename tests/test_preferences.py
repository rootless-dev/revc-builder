"""The Builder remembers the last game folder the user chose."""

from __future__ import annotations

from pathlib import Path

from vcbuilder.preferences import Preferences


def test_remembers_the_last_game_folder(tmp_path):
    folder = tmp_path / "Vice City"
    folder.mkdir()
    Preferences(tmp_path / "data").remember_game_folder(folder)
    assert Preferences(tmp_path / "data").last_game_folder() == folder


def test_a_folder_that_no_longer_exists_is_forgotten(tmp_path):
    folder = tmp_path / "Vice City"
    folder.mkdir()
    preferences = Preferences(tmp_path / "data")
    preferences.remember_game_folder(folder)
    folder.rmdir()
    assert preferences.last_game_folder() is None


def test_nothing_remembered_yet(tmp_path):
    assert Preferences(tmp_path / "data").last_game_folder() is None


def test_an_unreadable_preferences_file_is_ignored(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "preferences.json").write_text("{not json", encoding="utf-8")
    assert Preferences(data).last_game_folder() is None


def test_remembering_keeps_other_keys(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "preferences.json").write_text('{"other": 1}', encoding="utf-8")
    folder = tmp_path / "Vice City"
    folder.mkdir()
    Preferences(data).remember_game_folder(folder)
    text = (data / "preferences.json").read_text(encoding="utf-8")
    assert '"other": 1' in text
    assert str(folder) in text
