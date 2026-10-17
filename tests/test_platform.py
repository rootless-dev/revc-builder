"""The platform seam: the selector, and the pipeline running against a fake platform."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.conftest import make_tree
from vcbuilder import platform as platforms
from vcbuilder.errors import UnsupportedPlatformError
from vcbuilder.events import StageFailed, StageFinished, StageStarted
from vcbuilder.gamefiles import load_required_files
from vcbuilder.install import CopyFailed
from vcbuilder.paths import Locations
from vcbuilder.platform.base import Platform, ToolsStatus
from vcbuilder.platform.macos import MacOSPlatform
from vcbuilder.session import BuildSession


def test_current_is_macos_on_darwin(monkeypatch):
    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    assert isinstance(platforms.current(), MacOSPlatform)


@pytest.mark.parametrize("name", ["linux", "win32", "android"])
def test_current_refuses_other_systems(monkeypatch, name):
    monkeypatch.setattr(platforms.sys, "platform", name)
    with pytest.raises(UnsupportedPlatformError) as raised:
        platforms.current()
    assert raised.value.code == "unsupported_platform"
    assert "macOS" in raised.value.user_message


def test_session_refuses_an_unsupported_system(monkeypatch, tmp_path):
    monkeypatch.setattr(platforms.sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        BuildSession(home=tmp_path)


class FakePlatform(Platform):
    """A platform made of plain files: no system tools, no compiler."""

    name = "fake"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def locations(self, home: Path) -> Locations:
        return Locations(
            home=home,
            builder_data=home / "fake-data",
            revc_user_files=home / "fake-revc",
            cache=home / "fake-cache",
            logs=home / "fake-logs",
        )

    def app_destination(self, locations: Locations, override: Path | None = None) -> Path:
        return override or locations.home / "fake-apps"

    def built_app(self, revc_build: Path) -> Path:
        return revc_build / "reVC.fakeapp"

    def steam_search_roots(self, home: Path) -> list[tuple[Path, Path]]:
        return [(home / "bottles", Path("steam/game"))]

    def copier(self, runner, stage):
        def copy(source: Path, destination: Path, clone: bool) -> None:
            self.calls.append(f"copy clone={clone}")
            if clone:
                raise CopyFailed("the fake file system cannot clone")
            shutil.copytree(source, destination, symlinks=True)

        return copy

    def volume_name(self, path: Path) -> str:
        return "the fake disk"

    def tools_present(self, runner) -> bool:
        self.calls.append("tools_present")
        return True

    def check_tools(self, runner) -> ToolsStatus:
        self.calls.append("check_tools")
        return ToolsStatus.READY

    def request_tools_install(self, runner) -> None:
        self.calls.append("request_tools_install")

    def host_architecture(self) -> str:
        return "fake64"

    def build_environment(self, base=None):
        return {"PATH": "/usr/bin:/bin"}

    def shared_library_name(self, stem: str, soversion: str) -> str:
        return f"lib{stem}.so.{soversion}"

    def dependency_cmake_definitions(self, arch: str, dependency: str):
        return {"FAKE_ARCH": arch}

    def verify_dependency_library(self, library, runner, *, stage) -> None:
        self.calls.append(f"verify_dependency_library {library.name}")

    def revc_cmake_definitions(self, prefix: Path, arch: str):
        return {"FAKE_PREFIX": str(prefix)}

    def verify_app(self, app: Path, runner, *, stage) -> None:
        self.calls.append(f"verify_app {app.name}")


def test_the_pipeline_runs_against_a_fake_platform(tmp_path):
    home = tmp_path / "home"
    game = make_tree(tmp_path / "Vice City", load_required_files())
    fake = FakePlatform(tmp_path)
    events = []
    session = BuildSession(home=home, platform=fake, emit=events.append)
    locations = session.locations
    assert locations.cache == home / "fake-cache"
    assert session.log_path.parent == home / "fake-logs"

    # Stages 1 and 2 go through the platform's toolchain checks.
    first = session.build(game, start="validate", stop_after="tools")
    assert first.succeeded, first.error
    assert fake.calls == ["tools_present", "check_tools"]

    # Stages 6 and 7 (3 to 5 need the network and a compiler): a "built" app in the cache.
    make_tree(fake.built_app(locations.revc_build), ["Contents/reVC"], content=b"fake binary")
    second = session.build(game, start="verify")
    assert second.succeeded, second.error

    assert "verify_app reVC.fakeapp" in fake.calls
    assert session.installed_app == home / "fake-apps" / "reVC.fakeapp"
    assert (session.installed_app / "Contents" / "reVC").read_bytes() == b"fake binary"
    assert session.game_data == home / "fake-data" / "game"
    assert (session.game_data / "data" / "gta_vc.dat").is_file()
    assert (home / "fake-revc" / "reVC.ini").read_text() == f"[General]\nGamePath={session.game_data}\n"
    assert "copy clone=True" in fake.calls and "copy clone=False" in fake.calls
    started = [e.stage for e in events if isinstance(e, StageStarted)]
    assert started == ["validate", "tools", "verify", "install"]
    assert not [e for e in events if isinstance(e, StageFailed)]
    assert [e.stage for e in events if isinstance(e, StageFinished)] == started


def test_steam_installs_come_from_the_platform_roots(tmp_path):
    home = tmp_path / "home"
    (home / "bottles" / "one" / "steam" / "game").mkdir(parents=True)
    session = BuildSession(home=home, platform=FakePlatform(tmp_path))
    assert session.steam_installs() == [home / "bottles" / "one" / "steam" / "game"]


def test_platform_specific_dependency_settings_come_from_the_platform():
    from vcbuilder.deps import DEPENDENCIES, dependency_configure_command

    openal = next(d for d in DEPENDENCIES if d.name == "openal-soft")
    paths = dict(cmake=Path("/c"), ninja=Path("/n"), source=Path("/s"), build=Path("/b"), prefix=Path("/p"), arch="x")
    on_macos = dependency_configure_command(openal, MacOSPlatform(), **paths)
    on_fake = dependency_configure_command(openal, FakePlatform(Path("/")), **paths)
    assert "-DALSOFT_REQUIRE_COREAUDIO=ON" in on_macos
    assert "-DHAVE_WFUNCTION_EFFECTS=OFF" in on_macos
    assert not any("COREAUDIO" in part or "@rpath" in part for part in on_fake)
    assert "-DALSOFT_EXAMPLES=OFF" in on_fake


def test_a_missing_lock_file_fails_the_build_with_the_lock_message(tmp_path, monkeypatch):
    import vcbuilder.session as session_module

    def missing():
        raise FileNotFoundError("sources.lock")

    monkeypatch.setattr(session_module, "lock_path", missing)
    events = []
    session = BuildSession(home=tmp_path / "home", platform=FakePlatform(tmp_path), emit=events.append)
    result = session.build(tmp_path, start="fetch")
    assert not result.succeeded
    assert result.error.code == "lock"
    assert events[-1] == StageFailed("fetch", result.error)
