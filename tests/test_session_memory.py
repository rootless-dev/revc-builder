"""The session remembers the chosen game folder and offers the Builder's own copy."""

from __future__ import annotations

from tests.conftest import make_tree
from tests.test_platform import FakePlatform
from vcbuilder.session import BuildSession

MARKERS = ["data/gta_vc.dat", "models/gta3.img"]


def _session(tmp_path):
    return BuildSession(home=tmp_path / "home", platform=FakePlatform(tmp_path))


def test_a_remembered_folder_is_offered_by_the_next_session(tmp_path):
    folder = make_tree(tmp_path / "Vice City", MARKERS)
    first = _session(tmp_path)
    first.remember_game_folder(folder)
    first.close()
    second = _session(tmp_path)
    assert second.remembered_game_folder() == folder
    second.close()


def test_the_installed_copy_is_offered_once_it_exists(tmp_path):
    session = _session(tmp_path)
    assert session.installed_game_folder() is None
    game = make_tree(session.locations.game_data, MARKERS)
    assert session.installed_game_folder() == game
    session.close()


def test_an_installed_copy_without_game_files_is_not_offered(tmp_path):
    session = _session(tmp_path)
    session.locations.game_data.mkdir(parents=True)
    assert session.installed_game_folder() is None
    session.close()
