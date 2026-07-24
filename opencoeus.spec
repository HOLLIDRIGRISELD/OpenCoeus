# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building OpenCoeus standalone executable."""
import sys
import os

block_cipher = None

a = Analysis(
    ['opencoeus/ui/app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'opencoeus',
        'opencoeus.config',
        'opencoeus.database',
        'opencoeus.engine',
        'opencoeus.executor',
        'opencoeus.folder_tree',
        'opencoeus.profiles',
        'opencoeus.rules_engine',
        'opencoeus.journal',
        'opencoeus.scanner',
        'opencoeus.safety',
        'opencoeus.hashing',
        'opencoeus.documents',
        'opencoeus.folder_classifier',
        'opencoeus.ui.theme',
        'opencoeus.ui.widgets',
        'opencoeus.ui.pages',
        'opencoeus.ui.dialogs',
        'opencoeus.ui.workers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OpenCoeus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
