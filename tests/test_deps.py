from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FakeRunner, make_tree
from vcbuilder.deps import DEPENDENCIES, dependency_configure_command, library_path
from vcbuilder.deps import verify_prefix as _verify_prefix
from vcbuilder.platform.macos import MacOSPlatform
from vcbuilder.errors import CompileError

PREFIX = Path("/cache/prefix")
MACOS = MacOSPlatform()


def verify_prefix(prefix, runner, *, stage):
    _verify_prefix(prefix, MACOS, runner, stage=stage)


def _library(dependency) -> str:
    return MACOS.shared_library_name(dependency.stem, dependency.soversion)


def _definitions(command):
    return {p[2:].partition("=")[0]: p[2:].partition("=")[2] for p in command if p.startswith("-D")}


def test_the_three_dependencies_produce_the_files_revc_expects():
    assert {d.name: _library(d) for d in DEPENDENCIES} == {
        "glfw": "libglfw.3.dylib",
        "openal-soft": "libopenal.1.dylib",
        "mpg123": "libmpg123.0.dylib",
    }


@pytest.mark.parametrize("dependency", DEPENDENCIES, ids=lambda d: d.name)
def test_dependency_configure_command(dependency):
    command = dependency_configure_command(
        dependency,
        MACOS,
        cmake=Path("/tools/cmake"),
        ninja=Path("/tools/ninja"),
        source=Path("/cache/src") / dependency.name,
        build=Path("/cache/build") / dependency.name,
        prefix=PREFIX,
        arch="arm64",
    )
    definitions = _definitions(command)
    assert command[command.index("-G") + 1] == "Ninja"
    assert definitions["CMAKE_INSTALL_NAME_DIR"] == "@rpath"
    assert definitions["CMAKE_INSTALL_PREFIX"] == "/cache/prefix"
    assert definitions["BUILD_SHARED_LIBS"] == "ON"
    assert definitions["CMAKE_BUILD_TYPE"] == "Release"
    assert definitions["CMAKE_OSX_ARCHITECTURES"] == "arm64"
    assert definitions["CMAKE_IGNORE_PREFIX_PATH"] == "/opt/homebrew;/usr/local;/opt/local"
    assert definitions["CMAKE_DISABLE_FIND_PACKAGE_PkgConfig"] == "ON"
    source = command[command.index("-S") + 1]
    if dependency.name == "mpg123":
        assert source.endswith("ports/cmake")
    for name, value in dependency.options.items():
        assert definitions[name] == value
    off_switches = [name for name, value in dependency.options.items() if value == "OFF"]
    assert off_switches, "examples, tests and utilities must be switched off"


def _prefix(tmp_path: Path) -> Path:
    prefix = tmp_path / "prefix"
    make_tree(prefix, [f"lib/{_library(d)}" for d in DEPENDENCIES])
    return prefix


def _otool_d(install_names: dict[str, str]):
    def respond(argv):
        if argv[0].endswith("otool") and argv[1] == "-D":
            name = Path(argv[2]).name
            return 0, f"{argv[2]}:\n{install_names.get(name, '@rpath/' + name)}\n"
        return 0, ""

    return respond


def test_verify_prefix_accepts_rpath_install_names(tmp_path):
    verify_prefix(_prefix(tmp_path), FakeRunner(responder=_otool_d({})), stage="deps")


def test_verify_prefix_rejects_absolute_install_names(tmp_path):
    runner = FakeRunner(responder=_otool_d({"libglfw.3.dylib": "/cache/prefix/lib/libglfw.3.dylib"}))
    with pytest.raises(CompileError):
        verify_prefix(_prefix(tmp_path), runner, stage="deps")


def test_verify_prefix_requires_every_library(tmp_path):
    prefix = _prefix(tmp_path)
    (prefix / "lib" / "libopenal.1.dylib").unlink()
    with pytest.raises(CompileError):
        verify_prefix(prefix, FakeRunner(responder=_otool_d({})), stage="deps")


def test_library_path_uses_the_platform_file_name():
    assert library_path(PREFIX, DEPENDENCIES[2], MACOS) == PREFIX / "lib" / "libmpg123.0.dylib"
