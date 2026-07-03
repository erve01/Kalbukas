#!/usr/bin/env bash
# Build the macOS disk image. Run on macOS after:
#   pyinstaller packaging/Kalbukas.spec --noconfirm
set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/Kalbukas.app"
VERSION=$(python -c "import dictation; print(dictation.__version__)")
ARCH=$(uname -m)   # arm64 (Apple Silicon) or x86_64 (Intel)
DMG="dist/Kalbukas-${VERSION}-${ARCH}.dmg"

[ -d "$APP" ] || { echo "error: $APP not found — run PyInstaller first" >&2; exit 1; }

STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # classic drag-to-install layout
rm -f "$DMG"
hdiutil create -volname "Kalbukas" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "Wrote $DMG"
