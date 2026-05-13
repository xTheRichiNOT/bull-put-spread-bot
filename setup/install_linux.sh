#!/bin/bash
# Bull Put Spread Bot — Linux/Ubuntu Server Setup
# Getestet auf: Ubuntu 22.04 / 24.04, Debian 12
# Aufruf: sudo bash setup/install_linux.sh
#
# Was installiert wird:
#   - Python 3.12 + Abhängigkeiten
#   - Java 17 (für IB Gateway)
#   - Xvfb (virtueller Bildschirm — kein Monitor nötig)
#   - IB Gateway (statt TWS)
#   - IBC (automatischer Login)
#   - systemd-Services für Gateway + Bot
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$(whoami)}"
USER_HOME=$(eval echo "~$INSTALL_USER")
IBC_DIR="/opt/ibc"
GATEWAY_DIR="/opt/ibgateway"

# Root-Check
if [ "$EUID" -ne 0 ]; then
    echo "❌  Bitte mit sudo ausführen: sudo bash setup/install_linux.sh"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Bull Put Spread Bot — Linux Server Setup                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "    Bot-Verzeichnis: $BOT_DIR"
echo "    Benutzer:        $INSTALL_USER"
echo ""

# ── Schritt 1: System-Pakete ─────────────────────────────────────────────────
echo "📦  Installiere System-Pakete..."
apt-get update -q
apt-get install -y -q \
    python3 python3-pip \
    openjdk-17-jre-headless \
    xvfb x11vnc \
    wget curl unzip \
    ca-certificates \
    > /dev/null
echo "    ✅ System-Pakete installiert"

# ── Schritt 2: Python-Abhängigkeiten ────────────────────────────────────────
echo ""
echo "📦  Installiere Python-Abhängigkeiten..."
pip3 install -q ib_insync yfinance
echo "    ✅ ib_insync, yfinance installiert"

# ── Schritt 3: IB Gateway ────────────────────────────────────────────────────
echo ""
echo "📥  Lade IB Gateway herunter..."
GW_URL="https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"
wget -q --show-progress -O /tmp/ibgateway_install.sh "$GW_URL"
chmod +x /tmp/ibgateway_install.sh

echo "    Installiere IB Gateway nach $GATEWAY_DIR..."
mkdir -p "$GATEWAY_DIR"
# Stille Installation (-q), Zielverzeichnis (-dir)
/tmp/ibgateway_install.sh -q -dir "$GATEWAY_DIR" 2>/dev/null || true
echo "    ✅ IB Gateway installiert"

# ── Schritt 4: IBC (Auto-Login) ──────────────────────────────────────────────
echo ""
echo "📥  Lade IBC herunter (automatischer Login)..."
IBC_VER=$(curl -s https://api.github.com/repos/IbcAlpha/IBC/releases/latest \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
IBC_URL="https://github.com/IbcAlpha/IBC/releases/download/v${IBC_VER}/IBCLinux-${IBC_VER}.zip"
wget -q --show-progress -O /tmp/ibc.zip "$IBC_URL"
mkdir -p "$IBC_DIR"
unzip -q -o /tmp/ibc.zip -d "$IBC_DIR"
chmod +x "$IBC_DIR"/*.sh 2>/dev/null || true
chmod +x "$IBC_DIR"/scripts/*.sh 2>/dev/null || true
echo "    ✅ IBC v${IBC_VER} installiert"

# ── Schritt 5: IBC-Konfiguration ────────────────────────────────────────────
echo ""
echo "⚙️   Erstelle IBC-Konfiguration..."
cat > "$IBC_DIR/config.ini" << 'EOF'
# IBC Konfiguration — Zugangsdaten für automatischen Login
# WICHTIG: Diese Datei enthält dein Passwort — Zugriffsrechte sind eingeschränkt.
IbLoginId=DEIN_IB_BENUTZERNAME
IbPassword=DEIN_IB_PASSWORT

# paper = Paper Trading (Port 4002)
# live  = Live Trading  (Port 4001)
TradingMode=paper

LogToConsole=yes
FIX=no
ReadOnlyLogin=no
EOF
chmod 600 "$IBC_DIR/config.ini"
chown "$INSTALL_USER:$INSTALL_USER" "$IBC_DIR/config.ini"
echo "    ✅ $IBC_DIR/config.ini erstellt (Rechte: 600)"
echo "    ⚠️   WICHTIG: Zugangsdaten eintragen!"
echo "         nano $IBC_DIR/config.ini"

# ── Schritt 6: Xvfb-Startskript (virtueller Bildschirm) ─────────────────────
cat > /usr/local/bin/start_ibgateway.sh << SCRIPT
#!/bin/bash
# Startet IB Gateway headless (ohne Monitor) via Xvfb
export DISPLAY=:1
Xvfb :1 -screen 0 1024x768x24 -nolisten tcp &
sleep 2
export TWS_MAJOR_VRSN=stable
"$IBC_DIR/scripts/ibcstart.sh" \\
    Gateway \\
    --tws-path="$GATEWAY_DIR" \\
    --ibc-path="$IBC_DIR" \\
    --ibc-ini="$IBC_DIR/config.ini" \\
    --trading-mode=\$(grep "^TradingMode=" "$IBC_DIR/config.ini" | cut -d= -f2 | tr -d '[:space:]')
SCRIPT
chmod +x /usr/local/bin/start_ibgateway.sh

# ── Schritt 7: systemd-Service für IB Gateway ────────────────────────────────
echo ""
echo "⚙️   Erstelle systemd-Services..."
cat > /etc/systemd/system/ibgateway.service << EOF
[Unit]
Description=Interactive Brokers Gateway (headless)
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=$INSTALL_USER
ExecStart=/usr/local/bin/start_ibgateway.sh
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── Schritt 8: systemd-Service für bot.py ────────────────────────────────────
cat > /etc/systemd/system/trading-bot.service << EOF
[Unit]
Description=Bull Put Spread Trading Bot
After=network.target ibgateway.service
# Warte bis IB Gateway bereit ist (60 Sekunden Login-Zeit)
ExecStartPre=/bin/sleep 60

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$BOT_DIR
ExecStart=/usr/bin/python3 $BOT_DIR/bot.py
Restart=on-failure
RestartSec=30
# Log in trades.log UND systemd journal
StandardOutput=append:$BOT_DIR/trades.log
StandardError=append:$BOT_DIR/trades.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ibgateway.service
systemctl enable trading-bot.service
echo "    ✅ ibgateway.service erstellt und aktiviert"
echo "    ✅ trading-bot.service erstellt und aktiviert"

# ── Schritt 9: Bot-Verzeichnis Rechte ────────────────────────────────────────
chown -R "$INSTALL_USER:$INSTALL_USER" "$BOT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Installation abgeschlossen!                         ║"
echo "║                                                          ║"
echo "║  NÄCHSTE SCHRITTE:                                       ║"
echo "║                                                          ║"
echo "║  1. IB-Zugangsdaten eintragen:                           ║"
echo "║     sudo nano /opt/ibc/config.ini                        ║"
echo "║                                                          ║"
echo "║  2. Account-Nummer in config.json eintragen:             ║"
echo "║     nano $BOT_DIR/config.json"
echo "║                                                          ║"
echo "║  3. Alles starten:                                       ║"
echo "║     sudo systemctl start ibgateway                       ║"
echo "║     sudo systemctl start trading-bot                     ║"
echo "║                                                          ║"
echo "║  SERVICE-BEFEHLE:                                        ║"
echo "║  Status:   systemctl status trading-bot                  ║"
echo "║  Stoppen:  systemctl stop trading-bot                    ║"
echo "║  Log live: journalctl -fu trading-bot                    ║"
echo "║        oder: tail -f $BOT_DIR/trades.log"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
