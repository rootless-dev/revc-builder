from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.conftest import make_tree
from vcbuilder.errors import DiskSpaceError, InstallError, InstallOverlapError
from vcbuilder.install import (
    CopyFailed,
    copy_game_data,
    edit_game_path,
    install_app,
    set_game_path,
)
from vcbuilder.platform.macos import MacOSPlatform

GAME = "/Users/someone/Library/Application Support/reVC Builder/game"


# --- GamePath editing (section 6.4) ------------------------------------------------


def test_game_path_replaces_existing_line_and_keeps_everything_else():
    original = (
        "; reVC settings\r\n"
        "[Display]\r\n"
        "Width = 1920\r\n"
        "\r\n"
        "[General]\r\n"
        "# keep this comment\r\n"
        "GamePath=/old/place\r\n"
        "Language = 0\r\n"
        "[Audio]\r\n"
        "Volume=100\r\n"
    )
    edited = edit_game_path(original, GAME)
    assert edited == original.replace("GamePath=/old/place", f"GamePath={GAME}")


def test_game_path_key_matches_with_spaces_and_only_in_reVC_case():
    original = "[ General ]\nfoo=1\n  GamePath  =  /old  \ngamepath=/other key to reVC\n"
    edited = edit_game_path(original, GAME)
    assert edited == f"[ General ]\nfoo=1\nGamePath={GAME}\ngamepath=/other key to reVC\n"


def test_a_section_in_another_case_is_not_general():
    """reVC reads [General] case-sensitively, so [general] is a different section."""
    original = "[general]\nGamePath=/old\n"
    assert edit_game_path(original, GAME) == f"[general]\nGamePath=/old\n\n[General]\nGamePath={GAME}\n"


def test_game_path_is_added_at_the_end_of_general_when_missing():
    original = "[Display]\nWidth=640\n[General]\nLanguage=0\n\n[Audio]\nVolume=3\n"
    edited = edit_game_path(original, GAME)
    assert edited == f"[Display]\nWidth=640\n[General]\nLanguage=0\nGamePath={GAME}\n\n[Audio]\nVolume=3\n"


def test_game_path_is_added_when_general_is_the_last_section_without_newline():
    original = "[General]\nLanguage=0"
    assert edit_game_path(original, GAME) == f"[General]\nLanguage=0\nGamePath={GAME}\n"


def test_game_path_creates_general_when_absent():
    original = "; comment\n[Display]\nWidth=640\n"
    assert edit_game_path(original, GAME) == f"; comment\n[Display]\nWidth=640\n\n[General]\nGamePath={GAME}\n"


def test_game_path_in_another_section_is_left_alone():
    original = "[Other]\nGamePath=/not/mine\n[General]\nLanguage=0\n"
    edited = edit_game_path(original, GAME)
    assert edited == f"[Other]\nGamePath=/not/mine\n[General]\nLanguage=0\nGamePath={GAME}\n"


def test_repeated_game_path_lines_collapse_into_one():
    """reVC's mINI keeps the last of repeated keys, so a stale later line must not survive."""
    original = "[General]\nGamePath=/a\nLanguage=0\nGamePath = /b\n[Other]\nGamePath=/c\n"
    assert edit_game_path(original, GAME) == f"[General]\nGamePath={GAME}\nLanguage=0\n[Other]\nGamePath=/c\n"


def test_set_game_path_creates_the_file_and_folder(tmp_path):
    ini = tmp_path / "reVC" / "reVC.ini"
    set_game_path(ini, Path(GAME))
    assert ini.read_text() == f"[General]\nGamePath={GAME}\n"


def test_set_game_path_keeps_other_bytes(tmp_path):
    ini = tmp_path / "reVC.ini"
    original = "[General]\r\nGamePath = C:\\Games\\VC\r\n[Controller]\r\nMethod=1\r\n"
    ini.write_bytes(original.encode())
    set_game_path(ini, Path(GAME))
    assert ini.read_bytes() == original.replace("GamePath = C:\\Games\\VC", f"GamePath={GAME}").encode()


# --- game data copy (section 6.3) ----------------------------------------------------


class RecordingCopier:
    """Copies with shutil and records how; ``fail_clone`` / ``fail_copy`` simulate errors."""

    def __init__(self, fail_clone: bool = False, fail_copy: bool = False):
        self.fail_clone = fail_clone
        self.fail_copy = fail_copy
        self.calls: list[tuple[str, Path, Path]] = []

    def __call__(self, source: Path, destination: Path, clone: bool) -> None:
        self.calls.append(("clone" if clone else "copy", source, destination))
        destination.mkdir(parents=True)
        (destination / "partial.bin").write_bytes(b"half")
        if (clone and self.fail_clone) or (not clone and self.fail_copy):
            raise CopyFailed("simulated failure")
        shutil.rmtree(destination)
        shutil.copytree(source, destination)


def _source(tmp_path: Path) -> Path:
    return make_tree(tmp_path / "source", ["data/gta_vc.dat", "models/gta3.img"], content=b"0123456789")


def _plenty(_path: Path) -> int:
    return 10**12


def test_copy_game_data_with_clone(tmp_path):
    data_dir = tmp_path / "Builder"
    copier = RecordingCopier()
    game = copy_game_data(_source(tmp_path), data_dir, copier=copier, free_space=_plenty)
    assert game == data_dir / "game"
    assert (game / "models" / "gta3.img").read_bytes() == b"0123456789"
    assert [call[0] for call in copier.calls] == ["clone"]
    assert copier.calls[0][2] == data_dir / "game.new"
    assert sorted(p.name for p in data_dir.iterdir()) == ["game"]


def test_copy_game_data_falls_back_to_a_normal_copy(tmp_path):
    data_dir = tmp_path / "Builder"
    copier = RecordingCopier(fail_clone=True)
    game = copy_game_data(_source(tmp_path), data_dir, copier=copier, free_space=_plenty)
    assert [call[0] for call in copier.calls] == ["clone", "copy"]
    assert not (game / "partial.bin").exists()
    assert (game / "data" / "gta_vc.dat").exists()


def test_copy_game_data_checks_free_space_before_a_normal_copy(tmp_path):
    data_dir = tmp_path / "Builder"
    copier = RecordingCopier(fail_clone=True)
    source = _source(tmp_path)  # 20 bytes; 10 % margin means 22 bytes are needed
    with pytest.raises(DiskSpaceError) as raised:
        copy_game_data(source, data_dir, copier=copier, free_space=lambda path: 21)
    assert [call[0] for call in copier.calls] == ["clone"]
    assert not (data_dir / "game.new").exists()
    assert raised.value.code == "disk_space"
    copy_game_data(source, data_dir, copier=RecordingCopier(fail_clone=True), free_space=lambda path: 22)


def test_failed_copy_leaves_previous_game_intact(tmp_path):
    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game", ["previous.txt"])
    with pytest.raises(InstallError):
        copy_game_data(
            _source(tmp_path), data_dir, copier=RecordingCopier(fail_clone=True, fail_copy=True), free_space=_plenty
        )
    assert (data_dir / "game" / "previous.txt").exists()
    assert sorted(p.name for p in data_dir.iterdir()) == ["game"]


def test_successful_copy_replaces_previous_game(tmp_path):
    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game", ["previous.txt"])
    game = copy_game_data(_source(tmp_path), data_dir, copier=RecordingCopier(), free_space=_plenty)
    assert not (game / "previous.txt").exists()
    assert sorted(p.name for p in data_dir.iterdir()) == ["game"]


def test_leftover_staging_directories_are_removed(tmp_path):
    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game.new", ["stale-new.txt"])
    make_tree(data_dir / "game.old", ["stale-old.txt"])
    game = copy_game_data(_source(tmp_path), data_dir, copier=RecordingCopier(), free_space=_plenty)
    assert sorted(p.name for p in data_dir.iterdir()) == ["game"]
    assert not (game / "stale-new.txt").exists()


def test_source_equal_to_game_is_used_in_place(tmp_path):
    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game", ["data/gta_vc.dat"])
    copier = RecordingCopier()
    assert copy_game_data(data_dir / "game", data_dir, copier=copier, free_space=_plenty) == data_dir / "game"
    assert copier.calls == []
    assert (data_dir / "game" / "data" / "gta_vc.dat").exists()


@pytest.mark.parametrize(
    "relative_source",
    ["Builder/game.new", "Builder/game.old", "Builder/game/models", "Builder", "."],
    ids=["game.new", "game.old", "inside-game", "data-dir", "data-dir-parent"],
)
def test_sources_overlapping_the_builder_data_directory_are_refused(tmp_path, relative_source):
    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game", ["models/gta3.img"])
    make_tree(data_dir / "game.new", ["x"])
    make_tree(data_dir / "game.old", ["x"])
    source = (tmp_path / relative_source).resolve()
    copier = RecordingCopier()
    with pytest.raises(InstallOverlapError):
        copy_game_data(source, data_dir, copier=copier, free_space=_plenty)
    assert copier.calls == []
    assert (data_dir / "game" / "models" / "gta3.img").exists()


# --- application install -----------------------------------------------------------


def _fake_app(path: Path, marker: str) -> Path:
    make_tree(path, ["Contents/MacOS/reVC", "Contents/Info.plist"], content=marker.encode())
    return path


def test_install_app_copies_and_replaces(tmp_path):
    built = _fake_app(tmp_path / "build" / "reVC.app", "new")
    destination = tmp_path / "Applications"
    _fake_app(destination / "reVC.app", "old")
    installed = install_app(built, destination)
    assert installed == destination / "reVC.app"
    assert (installed / "Contents" / "MacOS" / "reVC").read_bytes() == b"new"
    assert sorted(p.name for p in destination.iterdir()) == ["reVC.app"]


def test_choose_app_destination_prefers_applications(tmp_path):
    applications = tmp_path / "Applications"
    applications.mkdir()
    platform = MacOSPlatform(applications=applications)
    assert platform.app_destination(platform.locations(tmp_path / "home")) == applications


def test_choose_app_destination_falls_back_to_home_applications(tmp_path):
    applications = tmp_path / "Applications"
    applications.mkdir()
    applications.chmod(0o555)
    try:
        platform = MacOSPlatform(applications=applications)
        assert platform.app_destination(platform.locations(tmp_path / "home")) == tmp_path / "home" / "Applications"
    finally:
        applications.chmod(0o755)


def test_locations_follow_the_spec(tmp_path):
    locations = MacOSPlatform().locations(tmp_path)
    support = tmp_path / "Library" / "Application Support"
    assert locations.builder_data == support / "reVC Builder"
    assert locations.game_data == support / "reVC Builder" / "game"
    assert locations.revc_ini == support / "reVC" / "reVC.ini"
    assert locations.cache == tmp_path / "Library" / "Caches" / "reVC Builder"
    assert locations.logs == tmp_path / "Library" / "Logs" / "reVC Builder"
    assert locations.prefix == locations.cache / "prefix"


def test_an_explicit_app_destination_wins(tmp_path):
    platform = MacOSPlatform()
    assert platform.app_destination(platform.locations(tmp_path), tmp_path / "Apps") == tmp_path / "Apps"


def test_install_app_clones_first_and_falls_back_to_a_copy(tmp_path):
    built = _fake_app(tmp_path / "build" / "reVC.app", "new")
    copier = RecordingCopier(fail_clone=True)
    installed = install_app(built, tmp_path / "Applications", copier=copier)
    assert [call[0] for call in copier.calls] == ["clone", "copy"]
    assert (installed / "Contents" / "MacOS" / "reVC").read_bytes() == b"new"


def test_disk_space_error_names_the_startup_disk_for_front_ends(tmp_path):
    with pytest.raises(DiskSpaceError) as raised:
        copy_game_data(_source(tmp_path), tmp_path / "Builder", copier=RecordingCopier(fail_clone=True),
                       free_space=lambda path: 0, volume_name=lambda path: "")
    assert raised.value.params["startup_disk"] is True
    assert raised.value.params["needed_bytes"] == 22
    assert "the startup disk" in raised.value.user_message


def test_folders_owned_by_the_builder_fail_validation(tmp_path):
    from vcbuilder.gamefiles import ValidationStatus, validate_game_folder

    data_dir = tmp_path / "Builder"
    make_tree(data_dir / "game.old", ["data/gta_vc.dat", "models/gta3.img"])
    make_tree(data_dir / "game", ["data/gta_vc.dat", "models/gta3.img"])
    required = ["data/gta_vc.dat", "models/gta3.img"]
    assert validate_game_folder(data_dir / "game.old", required, builder_data=data_dir).status is ValidationStatus.BUILDER_FOLDER
    assert validate_game_folder(data_dir / "game", required, builder_data=data_dir).status is ValidationStatus.VALID
