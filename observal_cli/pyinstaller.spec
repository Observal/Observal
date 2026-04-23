# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building the observal CLI binary.

Produces a single-file executable containing the main CLI, shim, proxy,
and sandbox runner entry points.
"""

import sys
from pathlib import Path

block_cipher = None

spec_dir = Path(SPECPATH)
repo_root = spec_dir.parent

cli_dir = spec_dir

# Collect all CLI modules
cli_modules = [str(p) for p in cli_dir.glob("*.py") if p.name != "__pycache__"]

a = Analysis(
    [str(spec_dir / "main.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "observal_cli.shim",
        "observal_cli.proxy",
        "observal_cli.sandbox_runner",
        "typer",
        "typer.main",
        "typer.core",
        "click",
        "rich",
        "rich.console",
        "rich.table",
        "rich.panel",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "yaml",
        "questionary",
        "docker",
        "asyncpg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "cv2",
        "torch",
        "tensorflow",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="observal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=sys.platform != "win32",
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
