# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Bull Put Spread Bot
# Mac:     bash build_mac.command  → .app + DMG
# Windows: build_windows.bat       → single-file BullPutSpreadBot.exe
# Linux:   bash build_linux.sh     → one-folder BullPutSpreadBot/

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

_here = os.path.dirname(os.path.abspath(SPEC))
ICON_MAC = os.path.join(_here, "icons", "icon.icns")
ICON_WIN = os.path.join(_here, "icons", "icon.ico")
ICON_LIN = os.path.join(_here, "icons", "icon.png")

if sys.platform == "darwin":
    _icon = ICON_MAC
elif sys.platform == "win32":
    _icon = ICON_WIN
else:
    _icon = ICON_LIN

# collect_all holt Daten + Binaries + hiddenimports (fix für CTk Theme-JSON auf Windows)
ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[] + ctk_binaries,
    datas=[
        ("config.json",      "."),
        ("version.txt",      "."),
        ("requirements.txt", "."),
        ("icons/icon.png",   "icons"),
        ("icons/icon.ico",   "icons"),
    ] + ctk_datas,
    hiddenimports=[
        "bot",
        "certifi",
        "ib_insync",
        "ib_insync.ib",
        "ib_insync.contract",
        "ib_insync.order",
        "ib_insync.objects",
        "ib_insync.ticker",
        "eventkit",
        "yfinance",
        "customtkinter",
        "zoneinfo",
        "tzdata",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "darkdetect",
        "packaging",
        "packaging.version",
    ] + ctk_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Windows: Single-File EXE ──────────────────────────────────────────────────
if sys.platform == "win32":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="BullPutSpreadBot",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=_icon,
        exclude_binaries=False,
    )

# ── Mac / Linux: One-Folder ───────────────────────────────────────────────────
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="BullPutSpreadBot",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=_icon,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        name="BullPutSpreadBot",
    )

    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="BullPutSpreadBot.app",
            icon=ICON_MAC,
            bundle_identifier="com.bullputspreadbot.launcher",
            info_plist={
                "NSHighResolutionCapable": True,
                "LSBackgroundOnly": False,
            },
        )
