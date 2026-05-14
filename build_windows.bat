@echo off
chcp 65001 >nul
title Bull Put Spread Bot — Windows Build

echo.
echo ╔════════════════════════════════════════════════════════╗
echo ║   Bull Put Spread Bot — Windows Build                  ║
echo ╚════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

echo 📦  Installiere Build-Abhaengigkeiten...
pip install -q pyinstaller customtkinter ib_insync yfinance
if errorlevel 1 (
    echo ❌  pip fehlgeschlagen. Python installiert und im PATH?
    pause & exit /b 1
)
echo     OK

echo.
echo 🔨  Baue EXE...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

set BUILD_TMP=%TEMP%\bullputbot_build
set DIST_TMP=%TEMP%\bullputbot_dist
if exist "%BUILD_TMP%" rmdir /s /q "%BUILD_TMP%"
if exist "%DIST_TMP%"  rmdir /s /q "%DIST_TMP%"

pyinstaller bot.spec --noconfirm --workpath "%BUILD_TMP%" --distpath "%DIST_TMP%"
if errorlevel 1 (
    echo.
    echo ❌  Build fehlgeschlagen.
    pause & exit /b 1
)

mkdir dist
copy "%DIST_TMP%\BullPutSpreadBot.exe" "dist\BullPutSpreadBot.exe"
rmdir /s /q "%BUILD_TMP%" "%DIST_TMP%"

echo.
echo ╔════════════════════════════════════════════════════════╗
echo ║  ✅  Fertig!                                            ║
echo ║                                                        ║
echo ║  dist\BullPutSpreadBot.exe                             ║
echo ║  → Direkt an Kunden weitergeben                        ║
echo ║  → Doppelklick = startet sofort, kein Python noetig    ║
echo ╚════════════════════════════════════════════════════════╝
echo.
explorer dist
pause
