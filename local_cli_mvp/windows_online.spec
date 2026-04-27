# -*- mode: python ; coding: utf-8 -*-
"""
Windows 在线安装版 PyInstaller 规格文件。

目标产物：
- onedir GUI exe
- 首包只保留启动器
- 首次运行时自动下载完整瘦身运行包
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path.cwd().resolve()
LOCAL_CLI_DIR = PROJECT_ROOT / "local_cli_mvp"
ENTRY_SCRIPT = LOCAL_CLI_DIR / "online_gui_entry.py"
APP_NAME = "LocalTranscriptHelperOnline"
MANIFEST_FILE = LOCAL_CLI_DIR / "online_runtime_manifest.json"


datas: list[tuple[str, str]] = [
    (str(MANIFEST_FILE), "."),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "tkinter",
    "tkinter.messagebox",
    "requests",
]


a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT), str(LOCAL_CLI_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "av",
        "ctranslate2",
        "curl_cffi",
        "faster_whisper",
        "PIL",
        "docx",
        "fitz",
        "matplotlib",
        "nvidia",
        "numba",
        "onnxruntime",
        "pandas",
        "pptx",
        "pyarrow",
        "pymupdf",
        "rapidocr_onnxruntime",
        "scipy",
        "sqlalchemy",
        "streamlit",
        "sympy",
        "tensorflow",
        "tokenizers",
        "torch",
        "yt_dlp",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
