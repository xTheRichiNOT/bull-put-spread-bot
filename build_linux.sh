#!/bin/bash
# Bull Put Spread Bot — Linux Build
# Ergebnis: dist/BullPutSpreadBot/BullPutSpreadBot  (ausführbare Datei)
# Voraussetzung: python3-tk muss installiert sein
#   sudo apt install python3-tk   (Ubuntu/Debian)
#   sudo dnf install python3-tkinter   (Fedora/RHEL)
set -e
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Bull Put Spread Bot — Linux Build                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# tkinter prüfen (Linux hat es nicht immer dabei)
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "❌  tkinter fehlt. Bitte installieren:"
    echo "    Ubuntu/Debian:  sudo apt install python3-tk"
    echo "    Fedora/RHEL:    sudo dnf install python3-tkinter"
    echo ""
    read -p "Drücke Enter zum Beenden..."
    exit 1
fi

echo "📦  Installiere Build-Abhängigkeiten..."
pip3 install -q pyinstaller customtkinter ib_insync yfinance
echo "    ✅ Fertig"

echo ""
echo "🔨  Baue Binary..."
BUILD_TMP="/tmp/bullputbot_build"
DIST_TMP="/tmp/bullputbot_dist"
rm -rf build dist "$BUILD_TMP" "$DIST_TMP"
pyinstaller bot.spec --noconfirm \
    --workpath "$BUILD_TMP" \
    --distpath "$DIST_TMP"
mkdir -p dist
cp -R "$DIST_TMP/BullPutSpreadBot" dist/
rm -rf "$BUILD_TMP" "$DIST_TMP"

# Startskript für einfachen Aufruf
cat > dist/BullPutSpreadBot/start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
./BullPutSpreadBot
EOF
chmod +x dist/BullPutSpreadBot/start.sh

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅  Fertig!                                          ║"
echo "║                                                      ║"
echo "║  dist/BullPutSpreadBot/BullPutSpreadBot              ║"
echo "║  → Ordner an Kunden weitergeben                      ║"
echo "║  → ./BullPutSpreadBot  oder  bash start.sh           ║"
echo "║                                                      ║"
echo "║  Hinweis: Muss auf Linux gebaut werden               ║"
echo "║  (kein Cross-Compile von Mac/Windows möglich)        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
