# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['print_server_app.py'],
    pathex=[],
    binaries=[('SumatraPDF.exe', '.')],
    datas=[('icon.png', '.')],
    hiddenimports=['win32timezone', 'uvicorn.lifespan', 'uvicorn.loops', 'uvicorn.protocols'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='print_server_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Change from False to True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
