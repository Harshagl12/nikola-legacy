# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

launcher_dir = Path(SPECPATH)
project_root = launcher_dir.parent
datas = [
    (str(launcher_dir / 'nikola_icon.ico'), '.'),
    (str(project_root / 'backend'), 'backend'),
    (str(project_root / 'telegram_bot'), 'telegram_bot'),
    (str(project_root / 'electron_app'), 'electron_app'),
    (str(project_root / 'browser_extension'), 'browser_extension'),
]
binaries = []
hiddenimports = ['pystray._win32', 'PIL._tkinter_finder', 'PIL._imaging', 'PIL.Image', 'PIL.ImageGrab', 'win32gui']
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root), str(launcher_dir)],
    binaries=binaries,
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
    [],
    exclude_binaries=True,
    name='Nikola',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['nikola_icon.ico'],
    contents_directory='_internal',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Nikola',
)
