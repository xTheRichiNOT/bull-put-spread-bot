#!/bin/bash
# Bull Put Spread Bot — Mac Hintergrund-Service
# Installiert IB Gateway + IBC (Auto-Login) + launchd-Service
# Aufruf: bash setup/install_mac_service.sh
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IBC_DIR="$HOME/ibc"
GATEWAY_DIR="$HOME/ibgateway"
PLIST_NAME="com.tradingbot.bot"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Bull Put Spread Bot — Mac Hintergrund-Service       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Schritt 1: Python-Abhängigkeiten ────────────────────────────────────────
echo "📦  Installiere Python-Abhängigkeiten..."
pip3 install -q customtkinter ib_insync yfinance
echo "    ✅ Fertig"

# ── Schritt 2: IB Gateway herunterladen ─────────────────────────────────────
echo ""
echo "📥  Lade IB Gateway herunter..."
echo "    (Alternativ: https://www.interactivebrokers.com → Gateway)"
mkdir -p "$GATEWAY_DIR"
GW_URL="https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-macx64.dmg"
curl -L -o /tmp/ibgateway.dmg "$GW_URL" --progress-bar

echo "    Installiere IB Gateway..."
hdiutil attach /tmp/ibgateway.dmg -quiet
# IB Gateway DMG mounten und app kopieren
GW_APP=$(find /Volumes/IB\ Gateway* -name "*.app" 2>/dev/null | head -1)
if [ -n "$GW_APP" ]; then
    cp -R "$GW_APP" /Applications/ 2>/dev/null || true
    hdiutil detach /Volumes/IB\ Gateway* -quiet 2>/dev/null || true
    echo "    ✅ IB Gateway installiert"
else
    hdiutil detach /Volumes/IB\ Gateway* -quiet 2>/dev/null || true
    echo "    ⚠️  Manuelle Installation nötig: https://www.interactivebrokers.com → Gateway"
fi

# ── Schritt 3: IBC herunterladen (Auto-Login) ────────────────────────────────
echo ""
echo "📥  Lade IBC herunter (automatischer Login)..."
IBC_VER=$(curl -s https://api.github.com/repos/IbcAlpha/IBC/releases/latest \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
IBC_URL="https://github.com/IbcAlpha/IBC/releases/download/v${IBC_VER}/IBCMacOS-${IBC_VER}.zip"
curl -L -o /tmp/ibc.zip "$IBC_URL" --progress-bar
mkdir -p "$IBC_DIR"
unzip -q -o /tmp/ibc.zip -d "$IBC_DIR"
chmod +x "$IBC_DIR"/*.sh 2>/dev/null || true
echo "    ✅ IBC v${IBC_VER} installiert in $IBC_DIR"

# ── Schritt 4: IBC-Konfiguration erstellen ───────────────────────────────────
echo ""
echo "⚙️   IBC-Konfiguration..."
cat > "$IBC_DIR/config.ini" << 'EOF'
# IBC Konfiguration — Auto-Login für IB Gateway
# Trage deine Interactive Brokers Zugangsdaten ein:
IbLoginId=DEIN_IB_BENUTZERNAME
IbPassword=DEIN_IB_PASSWORT

# paper = Paper Trading (Port 4002)
# live  = Live Trading  (Port 4001)
TradingMode=paper

LogToConsole=yes
FIX=no
EOF
echo "    ✅ Konfiguration erstellt: $IBC_DIR/config.ini"
echo "    ⚠️   WICHTIG: Trage jetzt deine IB-Zugangsdaten ein!"
echo "         nano \"$IBC_DIR/config.ini\""

# ── Schritt 5: IB Gateway Startskript ────────────────────────────────────────
GATEWAY_START="$IBC_DIR/start_gateway.sh"
cat > "$GATEWAY_START" << SCRIPT
#!/bin/bash
# Startet IB Gateway mit automatischem Login via IBC
export TWS_MAJOR_VRSN=stable
export IBC_INI="$IBC_DIR/config.ini"
export TRADING_MODE=\$(grep "^TradingMode=" "\$IBC_INI" | cut -d= -f2 | tr -d '[:space:]')
"$IBC_DIR/scripts/ibcstart.sh" Gateway \\
    --tws-path="/Applications/IB Gateway.app" \\
    --ibc-path="$IBC_DIR" \\
    --ibc-ini="\$IBC_INI" \\
    --trading-mode="\$TRADING_MODE"
SCRIPT
chmod +x "$GATEWAY_START"

# ── Schritt 6: launchd-Service für bot.py ────────────────────────────────────
echo ""
echo "⚙️   Erstelle launchd-Service (Auto-Start beim Mac-Login)..."
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$BOT_DIR/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$BOT_DIR</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>$BOT_DIR/trades.log</string>
    <key>StandardErrorPath</key>
    <string>$BOT_DIR/trades.log</string>
    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH" 2>/dev/null || true
echo "    ✅ launchd-Service registriert"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅  Installation abgeschlossen!                     ║"
echo "║                                                      ║"
echo "║  Nächste Schritte:                                   ║"
echo "║  1. IB-Zugangsdaten eintragen:                       ║"
echo "║     nano ~/ibc/config.ini                            ║"
echo "║                                                      ║"
echo "║  2. IB Gateway starten:                              ║"
echo "║     bash ~/ibc/start_gateway.sh                      ║"
echo "║                                                      ║"
echo "║  3. Bot starten:                                     ║"
echo "║     launchctl start com.tradingbot.bot               ║"
echo "║                                                      ║"
echo "║  Bot stoppen:                                        ║"
echo "║     launchctl stop com.tradingbot.bot                ║"
echo "║                                                      ║"
echo "║  Log live verfolgen:                                 ║"
echo "║     tail -f ~/VSC/trading\ bot/trades.log            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
