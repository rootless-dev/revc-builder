# PyInstaller spec for "reVC Builder.app" (spec section 10).
# Build with packaging/build_app.sh, which also signs (ad hoc), verifies and zips the app.
# -*- mode: python -*-

import os
from pathlib import Path

import cmake
import ninja

ROOT = Path(SPECPATH).resolve().parent
VERSION = "0.1.0"
TARGET_ARCH = os.environ.get("REVC_BUILDER_ARCH", "universal2")

cmake_data = Path(cmake.CMAKE_DATA)
cmake_share = next((cmake_data / "share").glob("cmake-*"))

datas = [
    (str(ROOT / "gui" / "style"), "gui/style"),
    (str(ROOT / "gui" / "i18n" / "revc_builder_pt_BR.qm"), "gui/i18n"),
    (str(ROOT / "vcbuilder" / "data"), "vcbuilder/data"),
    (str(ROOT / "sources.lock"), "vcbuilder/data"),
    (str(ROOT / "patches"), "vcbuilder/data/patches"),
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
