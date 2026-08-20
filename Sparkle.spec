# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ai_hiddenimports = [
    'torch',
    'transformers',
    'transformers.integrations.ggml',
    'transformers.modeling_gguf_pytorch_utils',
    'tokenizers',
    'safetensors',
    'gguf',
    'accelerate',
]
for package in ('transformers.models.lfm2', 'gguf', 'accelerate'):
    ai_hiddenimports += collect_submodules(package)

ai_datas = []
for distribution in (
    'torch',
    'transformers',
    'tokenizers',
    'safetensors',
    'gguf',
    'accelerate',
    'huggingface-hub',
):
    try:
        ai_datas += copy_metadata(distribution)
    except Exception:
        pass


a = Analysis(
    ['app_entry.py'],
    pathex=[],
    binaries=[],
    datas=[('frontend', 'frontend'), ('Icon.png', '.')] + ai_datas,
    hiddenimports=['remote_auth', 'remote_gateway', 'remote_runtime', 'remote_mcp', 'mcp.server.auth.provider', 'mcp.server.auth.settings', 'mcp.server.streamable_http', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'pystray._win32', 'webview.platforms.winforms', 'webview.platforms.edgechromium'] + ai_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3', 'gi'],
    noarchive=False,
    optimize=0,
)

mcp_a = Analysis(
    ['mcp_entry.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['remote_mcp', 'remote_auth', 'paths', 'mcp.server.auth.provider', 'mcp.server.auth.settings', 'mcp.server.streamable_http', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3', 'gi'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)
mcp_pyz = PYZ(mcp_a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Sparkle',
    icon='Icon.png',
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
)

mcp_exe = EXE(
    mcp_pyz,
    mcp_a.scripts,
    mcp_a.binaries,
    mcp_a.datas,
    [],
    name='SparkleMCP',
    icon='Icon.png',
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
)
