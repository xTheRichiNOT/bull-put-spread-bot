#!/bin/bash
# Bull Put Spread Bot — Auto-Updater (Linux Server / headless)
# Prüft stündlich auf neue Version und aktualisiert bot.py automatisch.
# Wird von bot-updater.timer ausgeführt — nicht manuell aufrufen nötig.
#
# Manuell ausführen:  bash /opt/trading-bot/setup/auto_update.sh
# Log anzeigen:       tail -f /opt/trading-bot/updater.log

RELEASES_URL="https://raw.githubusercontent.com/xTheRichiNOT/bull-put-spread-bot-releases/main"
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$BOT_DIR/version.txt"
BOT_FILE="$BOT_DIR/bot.py"
LOG_FILE="$BOT_DIR/updater.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

# ── Versionen vergleichen ─────────────────────────────────────────────────────
LOCAL_VERSION=$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")

REMOTE_VERSION=$(curl -sf --max-time 10 "$RELEASES_URL/version.txt" | tr -d '[:space:]')
if [ $? -ne 0 ] || [ -z "$REMOTE_VERSION" ]; then
    log "⚠️  GitHub nicht erreichbar — Update übersprungen"
    exit 0
fi

if [ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]; then
    log "✅  Aktuell: v$LOCAL_VERSION"
    exit 0
fi

log "🔄  Update gefunden: v$LOCAL_VERSION → v$REMOTE_VERSION"

# ── bot.py herunterladen (atomisch ersetzen) ──────────────────────────────────
log "📥  Lade bot.py herunter..."
TMP_FILE=$(mktemp)

if curl -sf --max-time 60 "$RELEASES_URL/bot.py" -o "$TMP_FILE"; then
    mv "$TMP_FILE" "$BOT_FILE"
    echo "$REMOTE_VERSION" > "$VERSION_FILE"
    log "✅  bot.py → v$REMOTE_VERSION"
else
    rm -f "$TMP_FILE"
    log "❌  Download fehlgeschlagen — bot.py unverändert"
    exit 1
fi

# ── Trading-Bot Service neustarten ───────────────────────────────────────────
if systemctl is-active --quiet trading-bot 2>/dev/null; then
    log "🔄  Starte trading-bot neu..."
    systemctl restart trading-bot
    log "✅  Service neugestartet mit v$REMOTE_VERSION"
else
    log "ℹ️   trading-bot Service läuft nicht — kein Neustart nötig"
fi

log "🚀  Update auf v$REMOTE_VERSION abgeschlossen"
