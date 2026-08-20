# -*- mode: python ; coding: utf-8 -*-

import re

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    copy_metadata,
)


ai_hiddenimports = [
    'torch',
    'transformers',
    'transformers.integrations.ggml',
    'transformers.modeling_gguf_pytorch_utils',
    'tokenizers',
    'safetensors',
    'gguf',
    'accelerate',
    'keyring',
    'keyring.backends.Windows',
    'win32ctypes',
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
    'keyring',
    'pywin32-ctypes',
):
    try:
        ai_datas += copy_metadata(distribution)
    except Exception:
        pass

# A CUDA build of torch pulls in separate nvidia-* distributions that hold the
# runtime DLLs (cublas, cudnn, cuda_runtime, ...). PyInstaller does not discover
# them from the torch hook, so collect every installed nvidia package explicitly.
nvidia_datas = []
nvidia_binaries = []
nvidia_hidden = []
from importlib.metadata import distributions as _distributions

for _dist in _distributions():
    _name = (_dist.metadata.get('Name') or '').lower()
    if not _name.startswith('nvidia-'):
        continue
    _pkg = re.sub(r'-cu\d+$', '', _name).replace('-', '.')
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        try:
            _d, _b, _h = collect_all(_name.replace('-', '.'))
        except Exception:
            continue
    nvidia_datas += _d
    nvidia_binaries += _b
    nvidia_hidden += _h


a = Analysis(
    ['app_entry.py'],
    pathex=[],
    binaries=[] + nvidia_binaries,
    datas=[('frontend', 'frontend'), ('Icon.png', '.')] + ai_datas + nvidia_datas,
    hiddenimports=['remote_auth', 'remote_gateway', 'remote_runtime', 'remote_mcp', 'mcp.server.auth.provider', 'mcp.server.auth.settings', 'mcp.server.streamable_http', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'pystray._win32', 'webview.platforms.winforms', 'webview.platforms.edgechromium'] + ai_hiddenimports + nvidia_hidden,
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
    upx_exclude=[
        'torch_cuda*.dll',
        'cudnn*.dll',
        'cublas*.dll',
        'cufft*.dll',
        'curand*.dll',
        'cusolver*.dll',
        'cusparse*.dll',
        'nvjpeg*.dll',
        'nvrtc*.dll',
        'cudart*.dll',
        'nccl*.dll',
        'nvToolsExt*.dll',
        '*.so',
    ],
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
