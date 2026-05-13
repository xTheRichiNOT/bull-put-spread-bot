#!/bin/bash
# Veröffentlicht eine neue Bot-Version ins öffentliche Releases-Repo.
# Aufruf: ./publish_release.sh
set -e

DEV_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASES_DIR="/tmp/bot-releases-publish"
RELEASES_REMOTE="https://github.com/xTheRichiNOT/bull-put-spread-bot-releases.git"

# Aktuelle Version lesen
VERSION=$(cat "$DEV_DIR/version.txt" | tr -d '[:space:]')

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Release veröffentlichen: v$VERSION"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Releases-Repo klonen / aktualisieren
if [ -d "$RELEASES_DIR/.git" ]; then
    echo "📥  Aktualisiere Releases-Repo..."
    git -C "$RELEASES_DIR" pull -q
else
    echo "📥  Klone Releases-Repo..."
    git clone -q "$RELEASES_REMOTE" "$RELEASES_DIR"
fi

# Release-Dateien kopieren
echo "📋  Kopiere Dateien..."
for FILE in bot.py launcher.py requirements.txt version.txt; do
    cp "$DEV_DIR/$FILE" "$RELEASES_DIR/$FILE"
    echo "    ✓ $FILE"
done

# Committen und pushen
cd "$RELEASES_DIR"
git add .
if git diff --cached --quiet; then
    echo ""
    echo "ℹ  Keine Änderungen — v$VERSION ist bereits aktuell."
else
    git commit -m "release v$VERSION"
    git push
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║   ✅  v$VERSION erfolgreich veröffentlicht!  ║"
    echo "║                                              ║"
    echo "║   Kunden sehen beim nächsten Start:          ║"
    echo "║   📦 Update verfügbar: v$VERSION             ║"
    echo "╚══════════════════════════════════════════════╝"
fi
echo ""
