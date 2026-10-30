# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the FinBoard Windows application."""

from pathlib import Path

ROOT = Path(SPECPATH)
RESOURCES = ROOT / "finboard" / "resources"
LOCALES = ROOT / "finboard" / "locales"

datas = [
    (str(RESOURCES / "finboard.ico"), "finboard/resources"),
    (str(RESOURCES / "finboard.png"), "finboard/resources"),
    (str(RESOURCES / "chevron-down.svg"), "finboard/resources"),
    (str(RESOURCES / "check.svg"), "finboard/resources"),
    (str(LOCALES / "en.json"), "finboard/locales"),
]

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FinBoard",
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
    name="FinBoard",
)
