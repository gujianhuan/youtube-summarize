"""
便携版运行时路径与资源解析工具。

统一处理 Windows 绿色包场景下的模型目录、输出目录、日志目录和
ffmpeg 路径，避免程序依赖当前工作目录。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen_runtime() -> bool:
    """判断当前是否运行在打包后的可执行文件环境中。"""

    return bool(getattr(sys, "frozen", False))


def get_source_root() -> Path:
    """返回源码根目录。"""

    return Path(__file__).resolve().parent


def get_runtime_root() -> Path:
    """返回当前运行时的根目录。

    - 开发环境：项目根目录
    - 打包环境：exe 所在目录
    """

    if is_frozen_runtime():
        return Path(sys.executable).resolve().parent
    return get_source_root()


def _iter_resource_roots() -> list[Path]:
    """按优先级枚举可能的资源根目录。"""

    runtime_root = get_runtime_root()
    source_root = get_source_root()
    candidates = [
        runtime_root,
        runtime_root / "local_cli_mvp",
        source_root,
        source_root / "local_cli_mvp",
    ]

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(candidate)
    return unique_candidates


def find_resource_dir(dir_name: str) -> Path | None:
    """查找便携版或开发环境中的资源目录。"""

    clean_name = str(dir_name or "").strip().strip("/\\")
    if not clean_name:
        return None

    for base_dir in _iter_resource_roots():
        candidate = (base_dir / clean_name).resolve()
        if candidate.exists():
            return candidate
    return None


def get_models_dir(create: bool = True) -> Path:
    """返回 Whisper 模型目录。"""

    env_override = os.environ.get("LOCAL_HELPER_MODELS_DIR", "").strip()
    if env_override:
        target_dir = Path(env_override).expanduser().resolve()
        if create:
            target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    existing = find_resource_dir("models")
    if existing is not None:
        return existing

    target_dir = (get_runtime_root() / "models").resolve()
    if create:
        target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def get_output_dir(name: str = "local_cli_mvp_output", create: bool = True) -> Path:
    """返回 transcript 默认输出目录。"""

    env_override = os.environ.get("LOCAL_HELPER_OUTPUT_DIR", "").strip()
    if env_override:
        target_dir = Path(env_override).expanduser().resolve()
    else:
        target_dir = (get_runtime_root() / name).resolve()
    if create:
        target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def get_logs_dir(name: str = "logs", create: bool = True) -> Path:
    """返回日志目录。"""

    env_override = os.environ.get("LOCAL_HELPER_LOGS_DIR", "").strip()
    if env_override:
        target_dir = Path(env_override).expanduser().resolve()
    else:
        target_dir = (get_runtime_root() / name).resolve()
    if create:
        target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def get_bundled_ffmpeg_exe() -> Path | None:
    """优先查找便携版自带的 ffmpeg 可执行文件。"""

    env_override = os.environ.get("LOCAL_HELPER_FFMPEG_EXE", "").strip()
    if env_override:
        candidate = Path(env_override).expanduser().resolve()
        if candidate.exists():
            return candidate

    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [
        get_runtime_root() / "ffmpeg" / executable_name,
        get_runtime_root() / executable_name,
        get_source_root() / "ffmpeg" / executable_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def configure_portable_environment() -> dict[str, str]:
    """配置便携版运行环境变量并返回关键路径信息。"""

    runtime_root = get_runtime_root().resolve()
    models_dir = get_models_dir(create=True).resolve()
    output_dir = get_output_dir(create=True).resolve()
    logs_dir = get_logs_dir(create=True).resolve()
    ffmpeg_exe = get_bundled_ffmpeg_exe()

    os.environ["LOCAL_HELPER_RUNTIME_ROOT"] = str(runtime_root)
    os.environ["LOCAL_HELPER_MODELS_DIR"] = str(models_dir)
    os.environ["LOCAL_HELPER_OUTPUT_DIR"] = str(output_dir)
    os.environ["LOCAL_HELPER_LOGS_DIR"] = str(logs_dir)

    if ffmpeg_exe is not None:
        ffmpeg_dir = str(ffmpeg_exe.parent)
        current_path = os.environ.get("PATH", "")
        path_entries = current_path.split(os.pathsep) if current_path else []
        if ffmpeg_dir not in path_entries:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path if current_path else ffmpeg_dir
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(ffmpeg_exe)

    return {
        "runtime_root": str(runtime_root),
        "models_dir": str(models_dir),
        "output_dir": str(output_dir),
        "logs_dir": str(logs_dir),
        "ffmpeg_exe": str(ffmpeg_exe) if ffmpeg_exe is not None else "",
    }
