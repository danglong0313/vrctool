# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_submodules


spec_base = Path(SPECPATH).resolve()
project_root = spec_base if (spec_base / "vrctool_app").exists() else spec_base.parent
exe_name = os.environ.get("VRCTOOL_EXE_NAME", "vrctool")
icon_path = Path(os.environ.get("VRCTOOL_ICON_PATH", project_root / "build" / "logo.ico"))

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("pydglab_ws")
    + collect_submodules("pythonosc")
    + collect_submodules("bleak")
)

datas = [
    (str(project_root / "vrctool_app" / "web"), "vrctool_app/web"),
    (str(project_root / "vrctool_app" / "assets"), "vrctool_app/assets"),
]

a = Analysis(
    [str(project_root / "vrctool_app" / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)
