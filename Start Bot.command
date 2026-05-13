#!/bin/bash
# Bull Put Spread Bot — Starter (Doppelklick zum Starten)
DIR="$(cd "$(dirname "$0")" && pwd)"

# Abhängigkeiten beim ersten Start automatisch installieren
if ! python3 -c "import customtkinter" 2>/dev/null; then
    echo "📦 Installiere Abhängigkeiten (einmalig)..."
    pip3 install -q customtkinter ib_insync yfinance
    echo "✅ Fertig"
fi

python3 "$DIR/launcher.py"
