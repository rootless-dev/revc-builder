# PyInstaller spec for "reVC Builder.app" (spec section 10).
# Build with packaging/build_app.sh, which also signs (ad hoc), verifies and zips the app.
# -*- mode: python -*-

import os
import shutil
import sys
from importlib.metadata import distribution
from pathlib import Path

import cmake
import ninja

ROOT = Path(SPECPATH).resolve().parent
VERSION = "0.1.0"
TARGET_ARCH = os.environ.get("REVC_BUILDER_ARCH", "universal2")

cmake_data = Path(cmake.CMAKE_DATA)
cmake_share = next((cmake_data / "share").glob("cmake-*"))


def wheel_licence(dist_name: str, file_name: str) -> Path:
    dist = distribution(dist_name)
    for entry in dist.files or []:
        if entry.parent.name == "licenses" and entry.name == file_name:
            return Path(dist.locate_file(entry))
    raise SystemExit(f"licence file {file_name} not found in the {dist_name} wheel")


# Licence texts shipped with the app (THIRD_PARTY_NOTICES.md lists what each covers).
licences = {
    "LICENSE.txt": ROOT / "LICENSE",
    "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
    "LGPL-3.0.txt": ROOT / "packaging" / "licenses" / "LGPL-3.0.txt",
    "GPL-3.0.txt": ROOT / "packaging" / "licenses" / "GPL-3.0.txt",
    "Python-LICENSE.txt": Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt",
    "CMake-LICENSE_BSD_3.txt": wheel_licence("cmake", "LICENSE_BSD_3"),
    "CMake-wheel-LICENSE_Apache_20.txt": wheel_licence("cmake", "LICENSE_Apache_20"),
    "Ninja-LICENSE_Apache_20.txt": wheel_licence("ninja", "LICENSE_Apache_20"),
}
# PyInstaller cannot rename data files, so stage them under their shipped names.
licence_dir = ROOT / "build" / "licenses"
shutil.rmtree(licence_dir, ignore_errors=True)
licence_dir.mkdir(parents=True)
for name, source in licences.items():
    shutil.copyfile(source, licence_dir / name)

datas = [
    (str(ROOT / "gui" / "style"), "gui/style"),
    (str(ROOT / "gui" / "i18n" / "revc_builder_pt_BR.qm"), "gui/i18n"),
    (str(ROOT / "vcbuilder" / "data"), "vcbuilder/data"),
    (str(ROOT / "sources.lock"), "vcbuilder/data"),
    (str(ROOT / "patches"), "vcbuilder/data/patches"),
    (str(ROOT / "renderers"), "vcbuilder/data/renderers"),
    (str(licence_dir), "licenses"),
    # CMake finds its modules relative to its executable: <bin>/../share/cmake-X.Y
    (str(cmake_share), f"tools/cmake/share/{cmake_share.name}"),
]

binaries = [
    (str(cmake_data / "bin" / "cmake"), "tools/cmake/bin"),
    (str(Path(ninja.BIN_DIR) / "ninja"), "tools/ninja"),
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="reVC Builder",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="reVC Builder")

app = BUNDLE(
    coll,
    name="reVC Builder.app",
    icon=str(ROOT / "packaging" / "icon.icns"),
    bundle_identifier="local.revcbuilder.builder",
    version=VERSION,
    info_plist={
        "CFBundleName": "reVC Builder",
        "CFBundleDisplayName": "reVC Builder",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en", "pt-BR"],
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
)
