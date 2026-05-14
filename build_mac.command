#!/bin/bash
# Bull Put Spread Bot — Mac Build
# Ergebnis: dist/BullPutSpreadBot.pkg  (Standard-macOS-Installer)
set -e
cd "$(dirname "$0")"

VERSION=$(cat version.txt 2>/dev/null || echo "1.0.0")

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Bull Put Spread Bot — Mac Build  v$VERSION"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Abhängigkeiten ─────────────────────────────────────────────────────────
echo "📦  Installiere Build-Abhängigkeiten..."
pip3 install -q pyinstaller customtkinter ib_insync yfinance
echo "    ✅ Fertig"

# ── 2. PyInstaller → .app ─────────────────────────────────────────────────────
echo ""
echo "🔨  Baue .app (PyInstaller)..."
BUILD_TMP="/tmp/bullputbot_build"
DIST_TMP="/tmp/bullputbot_dist"
rm -rf build dist pkg_root "$BUILD_TMP" "$DIST_TMP"
pyinstaller bot.spec --noconfirm \
    --workpath "$BUILD_TMP" \
    --distpath "$DIST_TMP"
mkdir -p dist
cp -R "$DIST_TMP/BullPutSpreadBot.app" dist/
rm -rf "$BUILD_TMP" "$DIST_TMP"
echo "    ✅ dist/BullPutSpreadBot.app erstellt"

# ── 3. DMG erstellen ──────────────────────────────────────────────────────────
echo ""
echo "💿  Erstelle DMG Installer..."
rm -rf dmg_staging
mkdir -p dmg_staging

cp -R "dist/BullPutSpreadBot.app" "dmg_staging/"
ln -s /Applications "dmg_staging/Applications"

VOL_NAME="BullPutSpreadBot v${VERSION}"
DMG_RW="dist/_BullPutSpreadBot_rw.dmg"
DMG_OUT="dist/BullPutSpreadBot-v${VERSION}.dmg"

# Read-Write DMG erstellen (zum Anpassen)
hdiutil create \
    -volname  "$VOL_NAME" \
    -srcfolder dmg_staging \
    -ov -format UDRW \
    "$DMG_RW" > /dev/null

# Mounten
DEVICE=$(hdiutil attach -readwrite -noverify -noautoopen "$DMG_RW" \
    | awk 'NR==1{print $1}')
sleep 2

# Fenster-Layout via AppleScript setzen
osascript << APPLESCRIPT
tell application "Finder"
    tell disk "$VOL_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 760, 440}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 120
        set position of item "BullPutSpreadBot.app" of container window to {150, 160}
        set position of item "Applications"          of container window to {410, 160}
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$DEVICE" > /dev/null

# Komprimiertes, read-only DMG erzeugen
hdiutil convert "$DMG_RW" -format UDZO -o "$DMG_OUT" > /dev/null
rm -f "$DMG_RW"
rm -rf dmg_staging

echo "    ✅ $DMG_OUT erstellt"

# ── Fertig ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅  Fertig!                                          ║"
echo "║                                                      ║"
echo "║  dist/BullPutSpreadBot-v${VERSION}.dmg               "
echo "║  → Doppelklick → App auf /Programme ziehen           ║"
echo "║  → App startet sofort, kein Python nötig             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
open dist/
read -p "Drücke Enter zum Schließen..."
