# -*- mode: python ; coding: utf-8 -*-
import os

is_share = os.environ.get('FENIX_SHARE_BUILD') == '1' or os.environ.get('FENIX_PUBLIC_BUILD') == '1' or os.environ.get('APP_BUILD_TYPE', '').lower() == 'public'
app_name = 'Opening Fenix Public' if is_share else 'Opening Fenix'

def get_safe_tree_datas(src_dir):
    datas = []
    if not os.path.exists(src_dir):
        return datas
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in ['.pgi', '.tmp', '.lock']:
                continue
            full_path = os.path.join(root, f)
            rel_dir = os.path.relpath(root, '.')
            datas.append((full_path, rel_dir))
    return datas

datas_list = [('assets', 'assets'), ('QUICKSTART.md', '.'), ('TECHNICAL_DEEP_DIVE.md', '.')]
if os.path.exists('repertoires'):
    datas_list.extend(get_safe_tree_datas('repertoires'))

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
