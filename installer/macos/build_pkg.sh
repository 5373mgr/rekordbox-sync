#!/bin/bash
# Builds rekordbox-sync.pkg from the PyInstaller outputs in dist/.
# Expects to be run from the repo root, after building:
#   pyinstaller --onefile --name rekordbox-sync run.py
#   pyinstaller --onefile --windowed --name rekordbox-sync-gui run_gui.py
#
# Usage: installer/macos/build_pkg.sh <version>

set -euo pipefail

VERSION="${1:?Usage: build_pkg.sh <version>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_ROOT="$ROOT_DIR/pkgroot"
OUT_DIR="$ROOT_DIR/dist_installer"

rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/Applications" "$PKG_ROOT/usr/local/bin" "$OUT_DIR"

cp -R "$ROOT_DIR/dist/rekordbox-sync-gui.app" "$PKG_ROOT/Applications/"
cp "$ROOT_DIR/dist/rekordbox-sync" "$PKG_ROOT/usr/local/bin/rekordbox-sync"
chmod +x "$PKG_ROOT/usr/local/bin/rekordbox-sync"

pkgbuild \
  --root "$PKG_ROOT" \
  --identifier com.5373mgr.rekordbox-sync \
  --version "$VERSION" \
  --install-location / \
  "$OUT_DIR/rekordbox-sync.pkg"

rm -rf "$PKG_ROOT"
echo "Built $OUT_DIR/rekordbox-sync.pkg"
