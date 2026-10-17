from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.conftest import FakeRunner, commit_all, git, make_repo, make_tree
from vcbuilder.compile import configure_command, restore_and_patch
from vcbuilder.platform.macos import (
    BUNDLED_DYLIBS,
    FORBIDDEN_PREFIXES,
    MacOSPlatform,
    find_macho_files,
    parse_otool_libraries,
)
from vcbuilder.errors import BundleError, CompileError
from vcbuilder.resources import lock_path, patch_files
from vcbuilder.sources import load_lock
from vcbuilder.runner import CommandRunner

PREFIX = Path("/cache/prefix")


def _configure() -> list[str]:
    return configure_command(
        MacOSPlatform(),
        cmake=Path("/tools/cmake"),
        ninja=Path("/tools/ninja"),
        source=Path("/cache/src/reVC"),
        build=Path("/cache/build/reVC"),
        prefix=PREFIX,
        arch="arm64",
    )


def _definitions(command: list[str]) -> dict[str, str]:
    result = {}
    for part in command:
        if part.startswith("-D"):
            name, _, value = part[2:].partition("=")
            result[name.split(":")[0]] = value
    return result


def test_configure_command_uses_ninja_and_the_pinned_tools():
    command = _configure()
    assert command[0] == "/tools/cmake"
    assert command[command.index("-G") + 1] == "Ninja"
    assert command[command.index("-S") + 1] == "/cache/src/reVC"
    assert command[command.index("-B") + 1] == "/cache/build/reVC"
    assert _definitions(command)["CMAKE_MAKE_PROGRAM"] == "/tools/ninja"


def test_configure_command_contains_every_variable_of_stage_5():
    definitions = _definitions(_configure())
    expected = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_OSX_ARCHITECTURES": "arm64",
        "CMAKE_PREFIX_PATH": "/cache/prefix",
        "CMAKE_IGNORE_PREFIX_PATH": "/opt/homebrew;/usr/local;/opt/local",
        "CMAKE_DISABLE_FIND_PACKAGE_PkgConfig": "ON",
        "OpenAL_DIR": "/cache/prefix/lib/cmake/OpenAL",
        "glfw3_DIR": "/cache/prefix/lib/cmake/glfw3",
        "mpg123_INCLUDE_DIR": "/cache/prefix/include",
        "mpg123_LIBRARIES": "/cache/prefix/lib/libmpg123.0.dylib",
        "REVC_MACOS_OPENAL_DYLIBS": "/cache/prefix/lib/libopenal.1.dylib",
        "REVC_MACOS_MPG123_DYLIBS": "/cache/prefix/lib/libmpg123.0.dylib",
        "REVC_MACOS_GLFW_DYLIBS": "/cache/prefix/lib/libglfw.3.dylib",
    }
    for name, value in expected.items():
        assert definitions.get(name) == value, name


def test_forbidden_prefixes_are_the_three_package_managers():
    assert FORBIDDEN_PREFIXES == ("/opt/homebrew", "/usr/local", "/opt/local")
    assert BUNDLED_DYLIBS == ("libopenal.1.dylib", "libmpg123.0.dylib", "libglfw.3.dylib")


# --- restore and patch -------------------------------------------------------------


@pytest.fixture
def checkout(tmp_path):
    """A local reVC-like checkout with a nested librw repository, both at their pins."""
    root = tmp_path / "reVC"
    make_repo(root, {"CMakeLists.txt": "line one\nline two\n", "src/a.c": "int a;\n"})
    librw = root / "vendor" / "librw"
    librw_pin = make_repo(librw, {"CMakeLists.txt": "project(librw)\n"})
    git("update-index", "--add", "--cacheinfo", f"160000,{librw_pin},vendor/librw", cwd=root)
    revc_pin = commit_all(root, "record the librw gitlink")
    return root, revc_pin, librw_pin


def _write_patches(directory: Path) -> list[Path]:
    directory.mkdir()
    first = directory / "0001-change-cmake.patch"
    first.write_text(
        "diff --git a/CMakeLists.txt b/CMakeLists.txt\n"
        "--- a/CMakeLists.txt\n"
        "+++ b/CMakeLists.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " line one\n"
        "-line two\n"
        "+line two patched\n"
    )
    second = directory / "0002-add-file.patch"
    second.write_text(
        "diff --git a/added.txt b/added.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/added.txt\n"
        "@@ -0,0 +1 @@\n"
        "+added by patch\n"
    )
    return [second, first]  # deliberately out of order


def test_restore_and_patch_applies_cleanly_twice(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    patches = _write_patches(tmp_path / "patches")
    runner = CommandRunner(emit=lambda event: None)
    for _ in range(2):
        restore_and_patch(root, revc_pin, librw_pin, patches, runner, stage="compile")
        assert (root / "CMakeLists.txt").read_text() == "line one\nline two patched\n"
        assert (root / "added.txt").read_text() == "added by patch\n"
        assert git("rev-parse", "HEAD", cwd=root) == revc_pin
        assert git("rev-parse", "HEAD", cwd=root / "vendor" / "librw") == librw_pin


def test_restore_discards_local_edits_and_moves_back_to_the_pins(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    librw = root / "vendor" / "librw"
    (librw / "CMakeLists.txt").write_text("edited\n")
    (root / "src" / "a.c").write_text("broken\n")
    (root / "later.txt").write_text("x\n")
    commit_all(root, "a commit after the pin")
    runner = CommandRunner(emit=lambda event: None)
    restore_and_patch(root, revc_pin, librw_pin, [], runner, stage="compile")
    assert git("rev-parse", "HEAD", cwd=root) == revc_pin
    assert (root / "src" / "a.c").read_text() == "int a;\n"
    assert not (root / "later.txt").exists()
    assert (librw / "CMakeLists.txt").read_text() == "project(librw)\n"


def test_a_patch_that_does_not_apply_is_a_compile_error(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    bad = tmp_path / "0001-bad.patch"
    bad.write_text(
        "diff --git a/CMakeLists.txt b/CMakeLists.txt\n"
        "--- a/CMakeLists.txt\n"
        "+++ b/CMakeLists.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " something else\n"
        "-entirely\n"
        "+nope\n"
    )
    with pytest.raises(CompileError):
        restore_and_patch(root, revc_pin, librw_pin, [bad], CommandRunner(emit=lambda e: None), stage="compile")


def test_repository_patches_exist_and_are_ordered():
    patches = patch_files()
    assert patches, "the CMake dependency patch must ship"
    assert [p.name for p in patches] == sorted(p.name for p in patches)
    assert "DEFINED CACHE{${PROJECT}_MACOS_${dependency}_DYLIBS}" in patches[0].read_text()


REFERENCE_CHECKOUT = Path(
    os.environ.get("VCBUILDER_REVC_CHECKOUT", Path.home() / "Library" / "Caches" / "reVC Builder" / "src" / "reVC")
)


@pytest.mark.skipif(not (REFERENCE_CHECKOUT / ".git").exists(), reason="no local reVC checkout to check against")
def test_repository_patches_apply_to_the_pinned_revc():
    """Checks against the index, which the compile stage leaves at the pinned commit."""
    head = subprocess.run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=REFERENCE_CHECKOUT, check=True,
                          capture_output=True, text=True).stdout.strip()
    assert head == load_lock(lock_path()).revc.commit, "the checkout is not at the pinned commit"
    for patch in patch_files():
        subprocess.run(["/usr/bin/git", "apply", "--check", "--cached", str(patch)], cwd=REFERENCE_CHECKOUT, check=True)


def verify_bundle(app, runner, *, stage):
    MacOSPlatform().verify_app(app, runner, stage=stage)


# --- bundle verification (macOS platform) -------------------------------------------------------------

MACHO_64 = bytes.fromhex("cffaedfe") + b"\0" * 28
FAT = bytes.fromhex("cafebabe") + b"\0\0\0\x02" + b"\0" * 24


def _bundle(tmp_path: Path) -> Path:
    app = tmp_path / "reVC.app"
    make_tree(app, ["Contents/Info.plist", "Contents/Resources/gamefiles/x.txt"], content=b"plain text")
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "reVC").write_bytes(MACHO_64)
    frameworks = app / "Contents" / "Frameworks"
    frameworks.mkdir()
    for name in BUNDLED_DYLIBS:
        (frameworks / name).write_bytes(FAT)
    return app


def _otool(clean: bool):
    def respond(argv):
        if argv[0].endswith("otool") and argv[1] == "-L":
            target = argv[2]
            lines = [f"{target}:"] + [f"\t@rpath/{name} (compatibility version 1.0.0)" for name in BUNDLED_DYLIBS]
            lines.append("\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)")
            if not clean and target.endswith("reVC"):
                lines.append("\t/opt/homebrew/opt/mpg123/lib/libmpg123.0.dylib (compatibility version 1.0.0)")
            return 0, "\n".join(lines) + "\n"
        if argv[0].endswith("otool") and argv[1] == "-l":
            return 0, "Load command 1\n      cmd LC_RPATH\n  cmdsize 48\n     path @executable_path/../Frameworks (offset 12)\n"
        return 0, ""

    return respond


def test_find_macho_files(tmp_path):
    app = _bundle(tmp_path)
    found = {p.relative_to(app).as_posix() for p in find_macho_files(app)}
    assert found == {"Contents/MacOS/reVC"} | {f"Contents/Frameworks/{n}" for n in BUNDLED_DYLIBS}


def test_parse_otool_libraries():
    output = (
        "/x/reVC.app/Contents/MacOS/reVC:\n"
        "\t@rpath/libopenal.1.dylib (compatibility version 1.0.0, current version 1.25.2)\n"
        "\t/System/Library/Frameworks/OpenGL.framework/Versions/A/OpenGL (compatibility version 1.0.0)\n"
    )
    assert parse_otool_libraries(output) == [
        "@rpath/libopenal.1.dylib",
        "/System/Library/Frameworks/OpenGL.framework/Versions/A/OpenGL",
    ]


def test_verify_bundle_accepts_a_clean_bundle(tmp_path):
    app = _bundle(tmp_path)
    runner = FakeRunner(responder=_otool(clean=True))
    verify_bundle(app, runner, stage="verify")
    commands = runner.commands()
    assert any(c[0].endswith("codesign") and "--verify" in c and "--deep" in c and "--strict" in c for c in commands)
    assert sum(1 for c in commands if c[0].endswith("otool") and c[1] == "-L") == 4


def test_verify_bundle_rejects_homebrew_links(tmp_path):
    app = _bundle(tmp_path)
    with pytest.raises(BundleError) as raised:
        verify_bundle(app, FakeRunner(responder=_otool(clean=False)), stage="verify")
    assert "/opt/homebrew" in str(raised.value.detail)


def test_verify_bundle_requires_the_three_dylibs(tmp_path):
    app = _bundle(tmp_path)
    (app / "Contents" / "Frameworks" / "libmpg123.0.dylib").unlink()
    with pytest.raises(BundleError):
        verify_bundle(app, FakeRunner(responder=_otool(clean=True)), stage="verify")


def test_verify_bundle_fails_when_codesign_fails(tmp_path):
    app = _bundle(tmp_path)
    base = _otool(clean=True)

    def respond(argv):
        if argv[0].endswith("codesign"):
            return 1, "invalid signature"
        return base(argv)

    with pytest.raises(BundleError):
        verify_bundle(app, FakeRunner(responder=respond), stage="verify")


def test_verify_bundle_strips_quarantine(tmp_path):
    app = _bundle(tmp_path)
    base = _otool(clean=True)
    state = {"quarantined": True}

    def respond(argv):
        if argv[0].endswith("xattr"):
            if "-d" in argv:
                state["quarantined"] = False
                return 0, ""
            return 0, "reVC.app: com.apple.quarantine: 0081;abc\n" if state["quarantined"] else ""
        return base(argv)

    runner = FakeRunner(responder=respond)
    verify_bundle(app, runner, stage="verify")
    assert not state["quarantined"]


def test_verify_bundle_requires_the_executable_to_link_the_bundled_copies(tmp_path):
    app = _bundle(tmp_path)
    base = _otool(clean=True)

    def respond(argv):
        if argv[0].endswith("otool") and argv[1] == "-L" and argv[2].endswith("MacOS/reVC"):
            return 0, f"{argv[2]}:\n\t/System/Library/Frameworks/OpenAL.framework/OpenAL (compatibility version 1.0.0)\n"
        return base(argv)

    with pytest.raises(BundleError) as raised:
        verify_bundle(app, FakeRunner(responder=respond), stage="verify")
    assert "@rpath/libopenal.1.dylib" in str(raised.value.detail)
