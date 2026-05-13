@echo off
chcp 65001 >nul
title Bull Put Spread Bot — Windows Installer

echo.
echo ╔══════════════════════════════════════════════╗
echo ║   Bull Put Spread Bot — Windows Installer    ║
echo ╚══════════════════════════════════════════════╝
echo.

:: ── Schritt 1: Python prüfen ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌  Python nicht gefunden.
    echo     Bitte installiere Python 3.10+ von https://www.python.org
    echo     Wichtig: "Add Python to PATH" beim Installieren anhaeken!
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo ✅  Python %PY_VER% gefunden

:: ── Schritt 2: IB-Software wählen ────────────────────────────────────────
echo.
echo Welche Interactive Brokers Software verwendest du?
echo.
echo   [1]  Trader Workstation (TWS)     - Standard, grafische Oberfläche
echo   [2]  IB Gateway                   - Leichtgewichtig, ideal für Hintergrund
echo.
set /p IB_CHOICE="Auswahl (1 oder 2): "

if "%IB_CHOICE%"=="2" (
    echo.
    echo 📥  IB Gateway wird heruntergeladen...
    curl -L -o "%TEMP%\ibgateway_install.exe" ^
        "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-windows-x64.exe"
    echo     Installiere IB Gateway ^(folge dem Installer^)...
    start /wait "" "%TEMP%\ibgateway_install.exe" -q
    echo ✅  IB Gateway installiert
    set IB_SOFTWARE=Gateway
) else (
    echo.
    echo ℹ   Bitte installiere TWS manuell von:
    echo     https://www.interactivebrokers.com ^> Handelsplattformen ^> TWS
    set IB_SOFTWARE=TWS
)

:: ── Schritt 3: Python-Umgebung ────────────────────────────────────────────
echo.
echo 📦  Erstelle virtuelle Python-Umgebung...
python -m venv .venv
if errorlevel 1 (
    echo ❌  Fehler beim Erstellen der virtuellen Umgebung.
    pause
    exit /b 1
)
echo ✅  Virtuelle Umgebung erstellt

echo.
echo 📥  Installiere Abhängigkeiten...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt -q
if errorlevel 1 (
    echo ❌  Fehler beim Installieren der Abhängigkeiten.
    pause
    exit /b 1
)
echo ✅  Abhängigkeiten installiert

:: ── Schritt 4: Starter erstellen ─────────────────────────────────────────
echo.
echo 🚀  Erstelle Starter-Datei...
(
echo @echo off
echo cd /d "%%~dp0"
echo .venv\Scripts\python launcher.py
) > "Start Bot.bat"
echo ✅  "Start Bot.bat" erstellt

:: ── Abschluss ─────────────────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║   Installation abgeschlossen!                        ║
echo ║                                                      ║
if "%IB_SOFTWARE%"=="Gateway" (
echo ║   IB Gateway starten:                                ║
echo ║   → Startmenü ^> IB Gateway ^> einloggen              ║
) else (
echo ║   TWS starten:                                       ║
echo ║   → TWS öffnen und einloggen                         ║
)
echo ║                                                      ║
echo ║   Bot starten:                                       ║
echo ║   → Doppelklick auf "Start Bot.bat"                  ║
echo ║                                                      ║
echo ║   Beim ersten Start öffnet sich ein                  ║
echo ║   Einrichtungsassistent automatisch.                 ║
echo ╚══════════════════════════════════════════════════════╝
echo.
pause
