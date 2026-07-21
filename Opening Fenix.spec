# -*- mode: python ; coding: utf-8 -*-
import os

is_share = os.environ.get('FENIX_SHARE_BUILD') == '1'
app_name = 'Opening Fenix Public' if is_share else 'Opening Fenix'

datas_list = [('assets', 'assets'), ('QUICKSTART.md', '.'), ('TECHNICAL_DEEP_DIVE.md', '.')]
if os.path.exists('profiles'):
    datas_list.append(('profiles', 'profiles'))
if os.path.exists('repertoires'):
    datas_list.append(('repertoires', 'repertoires'))
if not is_share:
    if os.path.exists('engines'):
        datas_list.append(('engines', 'engines'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas_list,
    hiddenimports=[],
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
    name=app_name,
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
    icon=['assets\\Logo\\favicon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
