# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for FinBoard Fluent (one-dir, Windows)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
RESOURCES = ROOT / "finboard_fluent" / "resources"
LOCALES = ROOT / "finboard_fluent" / "locales"

datas = [
    (str(RESOURCES / "finboard.ico"), "finboard_fluent/resources"),
    (str(RESOURCES / "finboard.png"), "finboard_fluent/resources"),
    (str(RESOURCES / "chevron-down.svg"), "finboard_fluent/resources"),
    (str(RESOURCES / "check.svg"), "finboard_fluent/resources"),
    (str(LOCALES / "en.json"), "finboard_fluent/locales"),
]
datas += collect_data_files("qfluentwidgets")

hiddenimports = [
    "PySide6.QtSvg",
    "openpyxl",
    "qframelesswindow",
    "darkdetect",
]
hiddenimports += collect_submodules("qfluentwidgets")

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FinBoardFluent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCES / "finboard.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FinBoardFluent",
)
