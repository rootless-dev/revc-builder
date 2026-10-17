#!/bin/sh
# Build, ad-hoc sign, verify and zip "reVC Builder.app" (spec section 10).
# Usage: packaging/build_app.sh   (with .venv set up from a universal2 Python, such as python.org's)
# REVC_BUILDER_ARCH=arm64 packaging/build_app.sh builds for one architecture instead.
# Output: dist/reVC Builder.app and dist/reVC-Builder-<version>-macOS.zip
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
APP="$ROOT/dist/reVC Builder.app"
VERSION=$("$PYTHON" -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' "$ROOT/pyproject.toml")
ZIP="$ROOT/dist/reVC-Builder-$VERSION-macOS.zip"

cd "$ROOT"
"$(dirname "$PYTHON")/pyside6-lrelease" gui/i18n/revc_builder_pt_BR.ts -qm gui/i18n/revc_builder_pt_BR.qm
"$PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath "$ROOT/dist" --workpath "$ROOT/build/pyinstaller" packaging/revc_builder.spec

# Sign everything ad hoc (no Apple Developer account; spec section 10), inside out.
/usr/bin/codesign --force --deep --sign - --timestamp=none "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"

rm -f "$ZIP"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo "Built $APP"
echo "Zipped $ZIP"
