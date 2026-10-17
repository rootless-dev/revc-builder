"""macOS: Apple Command Line Tools, ~/Library layout, APFS clones and app bundles.

``/usr/bin/clang`` is never run before ``xcode-select -p`` succeeds: on a Mac without the
tools, running it opens Apple's install dialog (spec section 7, page 3).
"""

from __future__ import annotations

import os
import platform as host
from pathlib import Path

from vcbuilder.errors import BundleError, CompileError
from vcbuilder.install import CopyFailed
from vcbuilder.paths import Locations
from vcbuilder.platform.base import Copier, Platform, ToolsStatus
from vcbuilder.runner import CommandFailed, CommandRunner
from vcbuilder.toolchain import tool_directories

XCODE_SELECT = "/usr/bin/xcode-select"
CLANG = "/usr/bin/clang"
OTOOL = "/usr/bin/otool"
CODESIGN = "/usr/bin/codesign"
XATTR = "/usr/bin/xattr"
CP = "/bin/cp"
QUARANTINE = "com.apple.quarantine"

#: Prefixes of Homebrew (arm64 and Intel) and MacPorts, whose libraries must never reach
#: the bundle (spec section 1.1, criterion 5).
PACKAGE_MANAGER_PREFIXES = ("/opt/homebrew", "/usr/local", "/opt/local")
FORBIDDEN_PREFIXES = PACKAGE_MANAGER_PREFIXES

#: Files reVC copies into Contents/Frameworks, in reVC's dependency order (spec F2), with the
#: <DEP> keys of reVC's REVC_MACOS_<DEP>_DYLIBS variables.
_REVC_KEYS = ("OPENAL", "MPG123", "GLFW")
BUNDLED_DYLIBS = ("libopenal.1.dylib", "libmpg123.0.dylib", "libglfw.3.dylib")

#: Environment variables that could point a build at a package manager.
_LEAKY_VARIABLES = (
    "HOMEBREW_PREFIX", "HOMEBREW_CELLAR", "HOMEBREW_REPOSITORY",
    "PKG_CONFIG_PATH", "PKG_CONFIG_LIBDIR", "CMAKE_PREFIX_PATH", "CMAKE_FRAMEWORK_PATH",
    "CMAKE_APPBUNDLE_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH",
    "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "CXX", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET",
)

_DEPENDENCY_DEFINITIONS = {
    "openal-soft": {
        # CoreAudio only: no backend may pick up a library from a package manager.
        "ALSOFT_BACKEND_COREAUDIO": "ON",
        "ALSOFT_REQUIRE_COREAUDIO": "ON",
        "ALSOFT_BACKEND_PIPEWIRE": "OFF",
        "ALSOFT_BACKEND_PULSEAUDIO": "OFF",
        "ALSOFT_BACKEND_JACK": "OFF",
        "ALSOFT_BACKEND_PORTAUDIO": "OFF",
        "ALSOFT_BACKEND_SDL2": "OFF",
        "ALSOFT_BACKEND_SDL3": "OFF",
        "ALSOFT_BACKEND_OBOE": "OFF",
        "ALSOFT_BACKEND_OPENSL": "OFF",
        "ALSOFT_BACKEND_SNDIO": "OFF",
        "ALSOFT_BACKEND_OSS": "OFF",
        "ALSOFT_BACKEND_SOLARIS": "OFF",
        # OpenAL Soft 1.25 adds -Werror=function-effects when the compiler supports
        # -Wfunction-effects, and AppleClang 21 (Xcode 27) reports two such diagnostics in
        # the CoreAudio backend. Pre-seeding the result of that compiler check skips both
        # flags; the diagnostic is a static-analysis aid and does not change the code.
        "HAVE_WFUNCTION_EFFECTS": "OFF",
    },
}

_STEAM_GAME = Path("drive_c/Program Files (x86)/Steam/steamapps/common/Grand Theft Auto Vice City")
_BOTTLE_CONTAINERS = (
    Path("Library/Application Support/CrossOver/Bottles"),
    Path("Library/Containers/com.isaacmarovitz.Whisky/Bottles"),
)

_MACHO_MAGICS = {
    bytes.fromhex(magic)
    for magic in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")
}


def deployment_target(arch: str) -> str:
    """reVC declares 11.0 for arm64. For x86_64 (best effort, untested) the dependencies use
    10.15, above reVC's own 10.12, as a conservative floor for OpenAL Soft's C++20 code."""
    return "11.0" if arch == "arm64" else "10.15"


class MacOSPlatform(Platform):
    name = "macOS"

    def __init__(self, applications: Path = Path("/Applications")) -> None:
        self.applications = applications

    # --- installed layout ---------------------------------------------------------------

    def locations(self, home: Path) -> Locations:
        library = home / "Library"
        support = library / "Application Support"
        return Locations(
            home=home,
            builder_data=support / "reVC Builder",
            # GetMacOSUserFilesFolder in reVC's src/skel/crossplatform.cpp (spec F4).
            revc_user_files=support / "reVC",
            cache=library / "Caches" / "reVC Builder",
            logs=library / "Logs" / "reVC Builder",
        )

    def app_destination(self, locations: Locations, override: Path | None = None) -> Path:
        if override is not None:
            return override
        if self.applications.is_dir() and os.access(self.applications, os.W_OK | os.X_OK):
            return self.applications
        return locations.home / "Applications"

    def built_app(self, revc_build: Path) -> Path:
        return revc_build / "src" / "reVC.app"

    def steam_search_roots(self, home: Path) -> list[tuple[Path, Path]]:
        return [(home / container, _STEAM_GAME) for container in _BOTTLE_CONTAINERS]

    def copier(self, runner: CommandRunner, stage: str) -> Copier:
        """``cp -cR`` makes an APFS clone (no extra space); ``cp -R`` is the normal copy."""

        def copy(source: Path, destination: Path, clone: bool) -> None:
            try:
                runner.run([CP, "-cR" if clone else "-R", source, destination], stage=stage)
            except CommandFailed as failure:
                raise CopyFailed(str(failure)) from failure

        return copy

    def volume_name(self, path: Path) -> str:
        existing = path
        while not existing.exists():
            existing = existing.parent
        device = existing.stat().st_dev
        mount = existing
        while mount.parent != mount and mount.parent.stat().st_dev == device:
            mount = mount.parent
        if str(mount) in ("/", "/System/Volumes/Data"):
            return ""
        return mount.name or str(mount)

    # --- toolchain ----------------------------------------------------------------------------

    def tools_present(self, runner: CommandRunner) -> bool:
        return runner.run([XCODE_SELECT, "-p"], stage="tools", check=False).returncode == 0

    def check_tools(self, runner: CommandRunner) -> ToolsStatus:
        if not self.tools_present(runner):
            return ToolsStatus.MISSING
        if runner.run([CLANG, "--version"], stage="tools", check=False).returncode != 0:
            return ToolsStatus.CLANG_FAILED
        return ToolsStatus.READY

    def request_tools_install(self, runner: CommandRunner) -> None:
        """Shows Apple's install dialog. The command returns at once; the install runs on its own."""
        runner.run([XCODE_SELECT, "--install"], stage="tools", check=False)

    def host_architecture(self) -> str:
        return "arm64" if host.machine() in {"arm64", "aarch64"} else "x86_64"

    def build_environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """The environment with Homebrew and MacPorts kept out of reach."""
        env = dict(os.environ if base is None else base)
        for name in _LEAKY_VARIABLES:
            env.pop(name, None)
        env["PATH"] = ":".join([*tool_directories(), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
        env["LC_ALL"] = "C"
        return env

    # --- CMake and the results -------------------------------------------------------------

    def shared_library_name(self, stem: str, soversion: str) -> str:
        return f"lib{stem}.{soversion}.dylib"

    def dependency_cmake_definitions(self, arch: str, dependency: str) -> dict[str, str]:
        return {
            "CMAKE_INSTALL_NAME_DIR": "@rpath",
            "CMAKE_OSX_ARCHITECTURES": arch,
            "CMAKE_OSX_DEPLOYMENT_TARGET": deployment_target(arch),
            "CMAKE_IGNORE_PREFIX_PATH": ";".join(PACKAGE_MANAGER_PREFIXES),
            "CMAKE_DISABLE_FIND_PACKAGE_PkgConfig": "ON",
            # Prefer plain libraries in the prefix over same-named macOS frameworks.
            "CMAKE_FIND_FRAMEWORK": "LAST",
            **_DEPENDENCY_DEFINITIONS.get(dependency, {}),
        }

    def verify_dependency_library(self, library: Path, runner: CommandRunner, *, stage: str) -> None:
        output = runner.run([OTOOL, "-D", library], stage=stage).output
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        name = lines[-1] if len(lines) >= 2 else ""
        expected = f"@rpath/{library.name}"
        if name != expected:
            raise CompileError(f"{library} has install name {name!r}, expected {expected!r}")

    def revc_cmake_definitions(self, prefix: Path, arch: str) -> dict[str, str]:
        lib = prefix / "lib"
        return {
            "CMAKE_OSX_ARCHITECTURES": arch,
            "CMAKE_IGNORE_PREFIX_PATH": ";".join(PACKAGE_MANAGER_PREFIXES),
            "CMAKE_DISABLE_FIND_PACKAGE_PkgConfig": "ON",
            # Read by reVC's top-level CMakeLists.txt (spec F3; patches/0001).
            **{f"REVC_MACOS_{key}_DYLIBS": str(lib / name) for key, name in zip(_REVC_KEYS, BUNDLED_DYLIBS)},
        }

    def verify_app(self, app: Path, runner: CommandRunner, *, stage: str) -> None:
        """Spec section 8, stage 6, plus criterion 5 of section 1.1."""
        frameworks = app / "Contents" / "Frameworks"
        missing = [name for name in BUNDLED_DYLIBS if not (frameworks / name).is_file()]
        if missing:
            raise BundleError(f"Contents/Frameworks is missing {', '.join(missing)}")

        problems = []
        machos = find_macho_files(app)
        if not machos:
            raise BundleError(f"{app} contains no Mach-O files")
        executables_link: set[str] = set()
        for macho in machos:
            relative = macho.relative_to(app)
            libraries = parse_otool_libraries(runner.run([OTOOL, "-L", macho], stage=stage).output)
            if relative.parts[:2] == ("Contents", "MacOS"):
                executables_link.update(libraries)
            for library in libraries:
                if _forbidden(library):
                    problems.append(f"{relative} links {library}")
            for rpath in parse_otool_rpaths(runner.run([OTOOL, "-l", macho], stage=stage).output):
                if _forbidden(rpath):
                    problems.append(f"{relative} has the run path {rpath}")
        # The game must actually use the bundled copies, not, say, Apple's OpenAL framework.
        for name in BUNDLED_DYLIBS:
            if f"@rpath/{name}" not in executables_link:
                problems.append(f"Contents/MacOS does not link @rpath/{name}")
        if problems:
            raise BundleError("the bundle is not self-contained:\n" + "\n".join(problems))

        if _has_quarantine(app, runner, stage):
            runner.log(stage, "Removing the quarantine attribute from the locally built app.")
            runner.run([XATTR, "-r", "-d", QUARANTINE, app], stage=stage, check=False)
            if _has_quarantine(app, runner, stage):
                raise BundleError(f"could not remove {QUARANTINE} from {app}")

        result = runner.run([CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", app], stage=stage, check=False)
        if result.returncode != 0:
            raise BundleError(f"codesign --verify failed:\n{result.output}")


def find_macho_files(bundle: Path) -> list[Path]:
    found = []
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                magic = stream.read(4)
        except OSError:
            continue
        if magic in _MACHO_MAGICS:
            found.append(path)
    return found


def parse_otool_libraries(output: str) -> list[str]:
    """Return the install names listed by ``otool -L`` (skipping the per-file header lines)."""
    libraries = []
    for line in output.splitlines():
        if not line.startswith("\t"):
            continue
        name = line.strip().split(" (compatibility version", 1)[0].strip()
        if name:
            libraries.append(name)
    return libraries


def parse_otool_rpaths(output: str) -> list[str]:
    rpaths = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            for following in lines[index + 1:index + 4]:
                stripped = following.strip()
                if stripped.startswith("path "):
                    rpaths.append(stripped[5:].rsplit(" (offset", 1)[0])
                    break
    return rpaths


def _forbidden(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES)


def _has_quarantine(app: Path, runner: CommandRunner, stage: str) -> bool:
    output = runner.run([XATTR, "-r", "-l", app], stage=stage, check=False).output
    return QUARANTINE in output
