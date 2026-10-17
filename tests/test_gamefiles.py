from __future__ import annotations

from pathlib import Path

from tests.conftest import make_tree
from vcbuilder.gamefiles import (
    ValidationStatus,
    detect_steam_installs as _detect,
    load_required_files,
    resolve_case_insensitive,
    validate_game_folder,
)

REQUIRED = [
    "data/gta_vc.dat",
    "models/gta3.img",
    "data/default.dat",
    "models/generic.txd",
    "text/american.gxt",
]

from vcbuilder.platform.macos import MacOSPlatform  # noqa: E402


def detect_steam_installs(home: Path) -> list[Path]:
    return _detect(MacOSPlatform().steam_search_roots(home))


STEAM_SUFFIX = "drive_c/Program Files (x86)/Steam/steamapps/common/Grand Theft Auto Vice City"
CROSSOVER = "Library/Application Support/CrossOver/Bottles"
WHISKY = "Library/Containers/com.isaacmarovitz.Whisky/Bottles"


def test_bundled_list_contains_the_files_revc_requires():
    required = load_required_files()
    lowered = {path.lower() for path in required}
    assert "data/gta_vc.dat" in lowered
    assert "models/gta3.img" in lowered
    assert len(required) == len(set(lowered)), "duplicate entries"
    assert all(not path.startswith("/") and "\\" not in path for path in required)


def test_valid_tree(tmp_path):
    make_tree(tmp_path, REQUIRED)
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert result.status is ValidationStatus.VALID
    assert result.missing == ()


def test_wrong_folder_is_not_a_game_folder(tmp_path):
    make_tree(tmp_path, ["Documents/notes.txt"])
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert result.status is ValidationStatus.NOT_GAME_FOLDER


def test_missing_folder_is_not_a_game_folder(tmp_path):
    result = validate_game_folder(tmp_path / "does-not-exist", required=REQUIRED)
    assert result.status is ValidationStatus.NOT_GAME_FOLDER


def test_folder_with_only_one_marker_is_incomplete(tmp_path):
    make_tree(tmp_path, ["models/gta3.img"])
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert result.status is ValidationStatus.INCOMPLETE
    assert "data/gta_vc.dat" in result.missing


def test_missing_files_are_listed_in_order(tmp_path):
    make_tree(tmp_path, ["data/gta_vc.dat", "models/gta3.img", "data/default.dat"])
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert result.status is ValidationStatus.INCOMPLETE
    assert result.missing == ("models/generic.txd", "text/american.gxt")


def test_only_the_first_ten_missing_files_are_shown(tmp_path):
    required = ["data/gta_vc.dat", "models/gta3.img"] + [f"audio/file{i:02}.wav" for i in range(15)]
    make_tree(tmp_path, required[:2])
    result = validate_game_folder(tmp_path, required=required)
    assert len(result.missing) == 15
    assert result.shown_missing == tuple(required[2:12])


def test_mixed_case_names_are_matched(tmp_path):
    make_tree(
        tmp_path,
        ["DATA/GTA_VC.DAT", "Models/Gta3.IMG", "data/Default.dat", "MODELS/GENERIC.TXD", "Text/American.gxt"],
    )
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert result.status is ValidationStatus.VALID


def test_resolve_case_insensitive(tmp_path):
    make_tree(tmp_path, ["Audio/Sfx.RAW"])
    assert resolve_case_insensitive(tmp_path, "audio/sfx.raw") == tmp_path / "Audio" / "Sfx.RAW"
    assert resolve_case_insensitive(tmp_path, "audio/missing.raw") is None


def test_a_directory_does_not_count_as_a_required_file(tmp_path):
    make_tree(tmp_path, ["models/gta3.img"])
    (tmp_path / "data" / "gta_vc.dat").mkdir(parents=True)
    result = validate_game_folder(tmp_path, required=REQUIRED)
    assert "data/gta_vc.dat" in result.missing


def _bottle(home: Path, container: str, bottle: str) -> Path:
    game = home / container / bottle / STEAM_SUFFIX
    game.mkdir(parents=True)
    return game


def test_steam_detection_without_bottles(tmp_path):
    assert detect_steam_installs(tmp_path) == []


def test_steam_detection_with_bottles_but_no_game(tmp_path):
    (tmp_path / CROSSOVER / "Steam" / "drive_c").mkdir(parents=True)
    (tmp_path / WHISKY / "Default").mkdir(parents=True)
    assert detect_steam_installs(tmp_path) == []


def test_steam_detection_finds_crossover_and_whisky(tmp_path):
    crossover = _bottle(tmp_path, CROSSOVER, "Steam")
    whisky = _bottle(tmp_path, WHISKY, "Gaming")
    assert detect_steam_installs(tmp_path) == [crossover, whisky]


def test_steam_detection_lists_every_bottle(tmp_path):
    first = _bottle(tmp_path, CROSSOVER, "A Bottle")
    second = _bottle(tmp_path, CROSSOVER, "B Bottle")
    third = _bottle(tmp_path, WHISKY, "W1")
    fourth = _bottle(tmp_path, WHISKY, "W2")
    assert detect_steam_installs(tmp_path) == [first, second, third, fourth]


def test_steam_detection_ignores_files_named_like_the_game(tmp_path):
    path = tmp_path / CROSSOVER / "Steam" / STEAM_SUFFIX
    path.parent.mkdir(parents=True)
    path.write_text("not a folder")
    assert detect_steam_installs(tmp_path) == []


def test_an_installer_folder_is_reported_as_an_installer(tmp_path):
    folder = make_tree(tmp_path / "download", ["setup.exe", "data-1.0.bin", "Readme.txt"])
    result = validate_game_folder(folder, required=REQUIRED)
    assert result.status is ValidationStatus.INSTALLER
    assert not result.is_valid


def test_installer_extensions_are_matched_case_insensitively(tmp_path):
    folder = make_tree(tmp_path / "download", ["DATA-1.CATALYST"])
    assert validate_game_folder(folder, required=REQUIRED).status is ValidationStatus.INSTALLER


def test_an_empty_or_unrelated_folder_is_not_an_installer(tmp_path):
    folder = make_tree(tmp_path / "photos", ["holiday.jpg"])
    assert validate_game_folder(folder, required=REQUIRED).status is ValidationStatus.NOT_GAME_FOLDER


def test_a_game_folder_with_an_exe_is_judged_by_its_game_files(tmp_path):
    # An installed game also has gta-vc.exe at the top; the marker files decide.
    folder = make_tree(tmp_path / "game", ["gta-vc.exe", "data/gta_vc.dat"])
    assert validate_game_folder(folder, required=REQUIRED).status is ValidationStatus.INCOMPLETE
