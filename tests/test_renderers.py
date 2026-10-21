"""Renderer selection, the pinned prebuilt renderer and the renderer overlays (Phase 2
design, section 7)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.conftest import FakeRunner, commit_all, git, make_repo, make_tree
from vcbuilder import renderers
from vcbuilder.__main__ import build_parser, main
from vcbuilder.compile import configure_command, restore_and_patch
from vcbuilder.errors import CompileError, LockError, RendererUnavailableError
from vcbuilder.paths import Locations
from vcbuilder.platform.macos import MacOSPlatform
from vcbuilder.resources import lock_path, renderers_dir
from vcbuilder.runner import CommandRunner
from vcbuilder.sources import load_lock, parse_lock

LOCK_HEAD = """
[sources.revc]
type = "git"
urls = ["https://example.invalid/reVC.git"]
commit = "1111111111111111111111111111111111111111"

[sources.librw]
type = "git"
path = "vendor/librw"
urls = ["https://example.invalid/librw.git"]
commit = "2222222222222222222222222222222222222222"

[sources.glfw]
type = "archive"
version = "3.5.1"
urls = ["https://example.invalid/glfw-3.5.1.zip"]
sha256 = "3333333333333333333333333333333333333333333333333333333333333333"
"""

RWGPU_ENTRY = """
[sources.rwgpu]
type = "archive"
renderer = "wgpu"
platform = "macos"
version = "0.1.0"
urls = ["https://example.invalid/rwgpu-0.1.0-macos-universal.tar.gz"]
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
placeholder = true
"""


# --- lock entries -------------------------------------------------------------------------


def test_lock_reads_renderer_platform_and_placeholder():
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY)
    rwgpu = lock.archive("rwgpu")
    assert (rwgpu.renderer, rwgpu.platform, rwgpu.placeholder) == ("wgpu", "macos", True)
    glfw = lock.archive("glfw")
    assert (glfw.renderer, glfw.platform, glfw.placeholder) == (None, None, False)


@pytest.mark.parametrize(
    "broken",
    [
        RWGPU_ENTRY.replace('renderer = "wgpu"', "renderer = 3"),
        RWGPU_ENTRY.replace('platform = "macos"', 'platform = ""'),
        RWGPU_ENTRY.replace("placeholder = true", 'placeholder = "yes"'),
    ],
)
def test_lock_rejects_malformed_renderer_fields(broken):
    with pytest.raises(LockError):
        parse_lock(LOCK_HEAD + broken)


def test_archives_for_filters_by_renderer_and_platform():
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY + RWGPU_ENTRY.replace("sources.rwgpu", "sources.rwgpu-linux")
                      .replace('platform = "macos"', 'platform = "linux"'))
    assert [a.name for a in lock.archives_for("gl3", "macos")] == ["glfw"]
    assert [a.name for a in lock.archives_for("wgpu", "macos")] == ["glfw", "rwgpu"]
    assert lock.renderer_library("wgpu", "macos").name == "rwgpu"
    assert lock.renderer_library("gl3", "macos") is None


def test_the_repository_lock_pins_the_published_renderer_for_macos():
    lock = load_lock(lock_path())
    library = lock.renderer_library("wgpu", MacOSPlatform.lock_platform)
    assert library is not None and library.name == "rwgpu"
    assert not library.placeholder and library.sha256 != "0" * 64
    assert f"/releases/download/rwgpu-v{library.version}/" in library.urls[0]
    assert library.urls[0].endswith(f"rwgpu-{library.version}-macos-universal.tar.gz")


# --- fetch plan ---------------------------------------------------------------------------------


def test_fetch_plan_refuses_a_placeholder_without_the_override():
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY)
    with pytest.raises(RendererUnavailableError):
        renderers.archives_to_fetch(lock, renderers.get("wgpu"), "macos", override=None)


def test_fetch_plan_skips_the_renderer_library_with_the_override(tmp_path):
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY)
    plan = renderers.archives_to_fetch(lock, renderers.get("wgpu"), "macos", override=tmp_path)
    assert [a.name for a in plan] == ["glfw"]


def test_fetch_plan_includes_a_published_library():
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY.replace("placeholder = true", ""))
    plan = renderers.archives_to_fetch(lock, renderers.get("wgpu"), "macos", override=None)
    assert [a.name for a in plan] == ["glfw", "rwgpu"]


def test_fetch_plan_for_gl3_never_needs_the_library():
    lock = parse_lock(LOCK_HEAD + RWGPU_ENTRY)
    assert [a.name for a in renderers.archives_to_fetch(lock, renderers.get("gl3"), "macos", override=None)] == ["glfw"]


# --- renderers -------------------------------------------------------------------------------------


def test_known_renderers_and_default():
    assert set(renderers.RENDERERS) == {"gl3", "wgpu"}
    assert renderers.DEFAULT_RENDERER == "wgpu"
    with pytest.raises(ValueError):
        renderers.get("vulkan")


def test_build_directory_per_renderer():
    locations = Locations(Path("/h"), Path("/d"), Path("/u"), Path("/c"), Path("/l"))
    assert locations.revc_build_for("gl3") == Path("/c/build/reVC")
    assert locations.revc_build_for("wgpu") == Path("/c/build/reVC-wgpu")


def _library_dir(root: Path, link_libs: str = "framework:Metal\nobjc\n\n") -> Path:
    make_tree(root, ["lib/librwgpu.a", "include/rwgpu.h"])
    (root / "lib" / "link-libs.txt").write_text(link_libs)
    return root


def test_rwgpu_library_reads_the_link_libraries(tmp_path):
    library = renderers.rwgpu_library(_library_dir(tmp_path / "rwgpu-0.1.0"), MacOSPlatform())
    assert library.library == tmp_path / "rwgpu-0.1.0" / "lib" / "librwgpu.a"
    assert library.include_dir == tmp_path / "rwgpu-0.1.0" / "include"
    assert library.link_libs == ["framework:Metal", "objc"]


def test_rwgpu_library_requires_every_file(tmp_path):
    root = _library_dir(tmp_path / "rwgpu")
    (root / "include" / "rwgpu.h").unlink()
    with pytest.raises(CompileError):
        renderers.rwgpu_library(root, MacOSPlatform())


def test_cmake_definitions_per_renderer(tmp_path):
    assert renderers.cmake_definitions(renderers.get("gl3"), None) == {"LIBRW_PLATFORM": "GL3"}
    library = renderers.rwgpu_library(_library_dir(tmp_path / "lib"), MacOSPlatform())
    definitions = renderers.cmake_definitions(renderers.get("wgpu"), library)
    assert definitions == {
        "LIBRW_PLATFORM": "WGPU",
        "RWGPU_LIBRARY": str(library.library),
        "RWGPU_INCLUDE_DIR": str(library.include_dir),
        "RWGPU_LINK_LIBS": "framework:Metal;objc",
    }
    command = configure_command(MacOSPlatform(), cmake=Path("/cmake"), ninja=Path("/ninja"), source=Path("/s"),
                                build=Path("/b"), prefix=Path("/p"), arch="arm64", extra=definitions)
    assert "-DLIBRW_PLATFORM=WGPU" in command
    assert "-DRWGPU_LINK_LIBS=framework:Metal;objc" in command


# --- overlays ------------------------------------------------------------------------------------


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "reVC"
    make_repo(root, {"CMakeLists.txt": "one\ntwo\n", "src/a.c": "int a;\n"})
    librw = root / "vendor" / "librw"
    librw_pin = make_repo(librw, {"src/engine.cpp": "engine\n"})
    git("update-index", "--add", "--cacheinfo", f"160000,{librw_pin},vendor/librw", cwd=root)
    revc_pin = commit_all(root, "record the librw gitlink")
    return root, revc_pin, librw_pin


def _overlay(base: Path) -> Path:
    overlay = base / "renderers" / "test"
    make_tree(overlay, ["librw/files/src/wgpu/driver.cpp", "revc/files/src/extras/extra.cpp"], content=b"ours\n")
    (overlay / "librw" / "patches").mkdir(parents=True)
    (overlay / "librw" / "patches" / "0001-engine.patch").write_text(
        "diff --git a/src/engine.cpp b/src/engine.cpp\n--- a/src/engine.cpp\n+++ b/src/engine.cpp\n"
        "@@ -1 +1 @@\n-engine\n+engine patched\n"
    )
    (overlay / "revc" / "patches").mkdir(parents=True)
    (overlay / "revc" / "patches" / "0001-cmake.patch").write_text(
        "diff --git a/CMakeLists.txt b/CMakeLists.txt\n--- a/CMakeLists.txt\n+++ b/CMakeLists.txt\n"
        "@@ -1,2 +1,2 @@\n one\n-two\n+two patched\n"
    )
    return overlay


def test_overlay_applies_cleanly_twice(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    overlay = renderers.Overlay.at(_overlay(tmp_path))
    runner = CommandRunner(emit=lambda event: None)
    for _ in range(2):
        restore_and_patch(root, revc_pin, librw_pin, [], runner, stage="compile", overlay=overlay)
        assert (root / "CMakeLists.txt").read_text() == "one\ntwo patched\n"
        assert (root / "vendor" / "librw" / "src" / "engine.cpp").read_text() == "engine patched\n"
        assert (root / "vendor" / "librw" / "src" / "wgpu" / "driver.cpp").read_text() == "ours\n"
        assert (root / "src" / "extras" / "extra.cpp").read_text() == "ours\n"


def test_restore_removes_overlay_files(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    runner = CommandRunner(emit=lambda event: None)
    restore_and_patch(root, revc_pin, librw_pin, [], runner, stage="compile", overlay=renderers.Overlay.at(_overlay(tmp_path)))
    restore_and_patch(root, revc_pin, librw_pin, [], runner, stage="compile")
    assert not (root / "src" / "extras" / "extra.cpp").exists()
    assert not (root / "vendor" / "librw" / "src" / "wgpu").exists()
    assert (root / "vendor" / "librw" / "src" / "engine.cpp").read_text() == "engine\n"


def test_a_missing_overlay_group_is_skipped(tmp_path):
    overlay = renderers.Overlay.at(tmp_path / "nothing-here")
    assert overlay.librw_patches == [] and overlay.revc_patches == []
    assert overlay.librw_files is None and overlay.revc_files is None


def test_a_bad_overlay_patch_is_a_compile_error(tmp_path, checkout):
    root, revc_pin, librw_pin = checkout
    overlay_dir = _overlay(tmp_path)
    (overlay_dir / "revc" / "patches" / "0001-cmake.patch").write_text(
        "diff --git a/CMakeLists.txt b/CMakeLists.txt\n--- a/CMakeLists.txt\n+++ b/CMakeLists.txt\n"
        "@@ -1,2 +1,2 @@\n nope\n-nope\n+nope\n"
    )
    with pytest.raises(CompileError):
        restore_and_patch(root, revc_pin, librw_pin, [], CommandRunner(emit=lambda e: None), stage="compile",
                          overlay=renderers.Overlay.at(overlay_dir))


def test_repository_overlays_exist():
    for name in renderers.RENDERERS:
        overlay = renderers.overlay_for(renderers.get(name))
        assert overlay.librw_patches, name
    wgpu = renderers.overlay_for(renderers.get("wgpu"))
    assert (wgpu.librw_files / "src" / "wgpu" / "wgpudevice.cpp").is_file()
    assert (wgpu.revc_files / "src" / "extras" / "custompipes_wgpu.cpp").is_file()
    assert wgpu.revc_patches
    assert renderers_dir().name == "renderers"


REFERENCE_CHECKOUT = Path(
    os.environ.get("VCBUILDER_REVC_CHECKOUT", Path.home() / "Library" / "Caches" / "reVC Builder" / "src" / "reVC")
)


@pytest.mark.skipif(not (REFERENCE_CHECKOUT / ".git").exists(), reason="no local reVC checkout to check against")
def test_repository_overlay_patches_apply_to_the_pinned_sources():
    """Checks against the indexes, which the compile stage leaves at the pinned commits."""
    for name in renderers.RENDERERS:
        overlay = renderers.overlay_for(renderers.get(name))
        for patch in overlay.revc_patches:
            subprocess.run(["/usr/bin/git", "apply", "--check", "--cached", str(patch)], cwd=REFERENCE_CHECKOUT, check=True)
        for patch in overlay.librw_patches:
            subprocess.run(["/usr/bin/git", "apply", "--check", "--cached", str(patch)],
                           cwd=REFERENCE_CHECKOUT / "vendor" / "librw", check=True)


# --- verification ------------------------------------------------------------------------------------


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "reVC.app"
    make_tree(app, ["Contents/MacOS/reVC"], content=bytes.fromhex("cffaedfe") + b"\0" * 28)
    return app


def _otool_links(*frameworks: str):
    def respond(argv):
        if argv[0].endswith("otool") and argv[1] == "-L":
            lines = [f"{argv[2]}:"] + [
                f"\t/System/Library/Frameworks/{f}.framework/Versions/A/{f} (compatibility version 1.0.0)" for f in frameworks
            ]
            return 0, "\n".join(lines) + "\n"
        return 0, ""

    return respond


def test_verify_renderer_wgpu_needs_metal_and_no_opengl(tmp_path):
    app = _app(tmp_path)
    platform = MacOSPlatform()
    platform.verify_renderer(app, "wgpu", FakeRunner(responder=_otool_links("Metal", "QuartzCore")), stage="verify")
    with pytest.raises(CompileError):
        platform.verify_renderer(app, "wgpu", FakeRunner(responder=_otool_links("Metal", "OpenGL")), stage="verify")
    with pytest.raises(CompileError):
        platform.verify_renderer(app, "wgpu", FakeRunner(responder=_otool_links("QuartzCore")), stage="verify")


def test_verify_renderer_gl3_needs_opengl(tmp_path):
    app = _app(tmp_path)
    platform = MacOSPlatform()
    platform.verify_renderer(app, "gl3", FakeRunner(responder=_otool_links("OpenGL")), stage="verify")
    with pytest.raises(CompileError):
        platform.verify_renderer(app, "gl3", FakeRunner(responder=_otool_links("Metal")), stage="verify")


def test_static_library_name():
    assert MacOSPlatform().static_library_name("rwgpu") == "librwgpu.a"


# --- CLI -----------------------------------------------------------------------------------------------


def test_cli_renderer_options():
    args = build_parser().parse_args(["/game"])
    assert args.renderer == renderers.DEFAULT_RENDERER and args.rwgpu_dir is None
    args = build_parser().parse_args(["/game", "--renderer", "wgpu", "--rwgpu-dir", "/lib"])
    assert args.renderer == "wgpu" and args.rwgpu_dir == Path("/lib")
    with pytest.raises(SystemExit):
        build_parser().parse_args(["/game", "--renderer", "metal"])


def test_cli_reads_the_override_from_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VCBUILDER_RWGPU_DIR", str(tmp_path / "lib"))
    folder = make_tree(tmp_path / "not-a-game", ["readme.txt"])
    code = main([str(folder), "--home", str(tmp_path / "home"), "--renderer", "wgpu"])
    assert code == 1
    log = next((tmp_path / "home" / "Library" / "Logs" / "reVC Builder").glob("build-*.log")).read_text()
    assert "renderer: wgpu" in log
    assert f"development override: {tmp_path / 'lib'}" in log
