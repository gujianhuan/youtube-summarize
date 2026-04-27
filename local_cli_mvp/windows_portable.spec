# -*- mode: python ; coding: utf-8 -*-
"""
Windows 便携版 PyInstaller 规格文件。

目标产物：
- onedir 绿色目录
- GUI exe
- 自动收集 faster-whisper / ctranslate2 / yt-dlp 等依赖
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


PROJECT_ROOT = Path.cwd().resolve()
LOCAL_CLI_DIR = PROJECT_ROOT / "local_cli_mvp"
ENTRY_SCRIPT = LOCAL_CLI_DIR / "portable_gui_entry.py"
APP_NAME = "LocalTranscriptHelper"


def collect_package_assets(package_name: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """安全收集三方包的资源和动态库。"""

    datas: list[tuple[str, str]] = []
    binaries: list[tuple[str, str]] = []
    try:
        datas.extend(collect_data_files(package_name, include_py_files=False))
    except Exception:
        pass
    try:
        binaries.extend(collect_dynamic_libs(package_name))
    except Exception:
        pass
    return datas, binaries


datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "faster_whisper",
    "tkinter",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkinter.ttk",
    "yt_dlp",
    "yt_dlp.utils",
]


for package_name in [
    "av",
    "ctranslate2",
    "curl_cffi",
    "faster_whisper",
    "tokenizers",
]:
    pkg_datas, pkg_binaries = collect_package_assets(package_name)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)


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
        "torch",
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
