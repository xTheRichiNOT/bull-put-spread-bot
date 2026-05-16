#!/bin/bash
# Veröffentlicht eine neue Bot-Version.
#
# Verwendung:
#   ./publish_release.sh              → Source-Update (bestehende User, sofort)
#   ./publish_release.sh --release    → Source-Update + Git-Tag pushen
#                                       → GitHub Actions baut Mac DMG, Windows EXE, Linux
#                                       → GitHub Release wird automatisch erstellt
set -e

DEV_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASES_DIR="/tmp/bot-releases-publish"
RELEASES_REMOTE="https://github.com/xTheRichiNOT/bull-put-spread-bot-releases.git"

# Flag auswerten
BUILD_RELEASE=false
for arg in "$@"; do
    [[ "$arg" == "--release" ]] && BUILD_RELEASE=true
done

# Aktuelle Version lesen
VERSION=$(cat "$DEV_DIR/version.txt" | tr -d '[:space:]')

echo ""
if [ "$BUILD_RELEASE" = true ]; then
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Full Release veröffentlichen: v$VERSION"
echo "║   (Source + Mac DMG + Windows EXE + Linux)           ║"
echo "╚══════════════════════════════════════════════════════╝"
else
echo "╔══════════════════════════════════════════════╗"
echo "║   Source-Update veröffentlichen: v$VERSION"
echo "╚══════════════════════════════════════════════╝"
fi
echo ""

# ── 1. Source-Dateien ins Releases-Repo pushen ────────────────────────────────
# (Bestehende Nutzer erhalten dadurch sofort das Update beim nächsten Start)

if [ -d "$RELEASES_DIR/.git" ]; then
    echo "📥  Aktualisiere Releases-Repo..."
    git -C "$RELEASES_DIR" pull -q
else
    echo "📥  Klone Releases-Repo..."
    git clone -q "$RELEASES_REMOTE" "$RELEASES_DIR"
fi

echo "📋  Kopiere Dateien..."
for FILE in bot.py launcher.py backtest.py shadow_analyze.py requirements.txt version.txt; do
    cp "$DEV_DIR/$FILE" "$RELEASES_DIR/$FILE"
    echo "    ✓ $FILE"
done
cp -r "$DEV_DIR/icons" "$RELEASES_DIR/"
echo "    ✓ icons/"

cd "$RELEASES_DIR"
git add .
if git diff --cached --quiet; then
    echo ""
    echo "ℹ  Keine Änderungen — v$VERSION ist bereits aktuell."
    SOURCE_CHANGED=false
else
    git commit -m "release v$VERSION"
    git push
    SOURCE_CHANGED=true
    echo ""
    echo "  ✅  Source v$VERSION gepusht → bestehende User erhalten Update"
fi

# ── 2. (Optional) Git-Tag pushen → GitHub Actions baut Binaries ──────────────
if [ "$BUILD_RELEASE" = true ]; then
    echo ""
    echo "🏷️   Git-Tag v$VERSION pushen → startet GitHub Actions Build..."

    cd "$DEV_DIR"

    # Dev-Repo committen falls ungespeicherte Änderungen in Versions-Dateien
    git add version.txt launcher.py bot.py requirements.txt 2>/dev/null || true
    if ! git diff --cached --quiet 2>/dev/null; then
        git commit -m "release v$VERSION"
    fi

    # Tag erstellen (überschreiben falls schon vorhanden)
    git tag -f "v$VERSION"
    git push origin "v$VERSION" --force

    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║   ✅  v$VERSION vollständig veröffentlicht!           ║"
    echo "║                                                      ║"
    echo "║   GitHub Actions baut jetzt:                         ║"
    echo "║   🍎  Mac DMG     (macos-latest)                     ║"
    echo "║   🪟  Windows EXE (windows-latest)                   ║"
    echo "║   🐧  Linux tar.gz (ubuntu-latest)                   ║"
    echo "║                                                      ║"
    echo "║   Status: github.com/xTheRichiNOT/                   ║"
    echo "║           bull-put-spread-bot/actions                ║"
    echo "╚══════════════════════════════════════════════════════╝"
else
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║   ✅  Source v$VERSION veröffentlicht!       ║"
    echo "║                                              ║"
    echo "║   Kunden sehen beim nächsten Start:          ║"
    echo "║   📦 Update verfügbar: v$VERSION             ║"
    echo "║                                              ║"
    echo "║   Für Installer-Build:                       ║"
    echo "║   ./publish_release.sh --release             ║"
    echo "╚══════════════════════════════════════════════╝"
fi
echo ""
