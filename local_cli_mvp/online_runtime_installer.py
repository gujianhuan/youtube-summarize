"""
在线安装版运行时下载器。

职责：
- 首次运行时下载完整的“最小内核瘦身包”
- 将运行包解压到用户目录，避免写入受限的 Program Files
- 让在线安装版首包只保留启动器，而不是再携带本地转写运行库
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


APP_VENDOR_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "LocalTranscriptHelper"
APP_RUNTIME_DIR = APP_VENDOR_DIR / "portable"
RUNTIME_STATE_FILE = APP_VENDOR_DIR / "online-launcher-state.json"
MANIFEST_FILE_NAME = "online_runtime_manifest.json"
DEFAULT_EXECUTABLE_NAME = "LocalTranscriptHelper.exe"
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE = 1024 * 1024

ProgressCallback = Callable[[str], None] | None


@dataclass(frozen=True)
class RuntimeManifest:
    """在线安装版运行包清单。"""

    version: str
    package_url: str
    package_sha256: str = ""
    executable_name: str = DEFAULT_EXECUTABLE_NAME


DEFAULT_RUNTIME_MANIFEST = RuntimeManifest(
    version="2026-04-23-online-launcher-v1",
    package_url="",
    package_sha256="",
    executable_name=DEFAULT_EXECUTABLE_NAME,
)


def _log(message: str, callback: ProgressCallback = None) -> None:
    """统一输出安装日志。"""

    logging.info(message)
    if callback:
        callback(message)


def get_runtime_dirs() -> dict[str, Path]:
    """返回在线安装版使用的用户级目录。"""

    runtime_dir = APP_RUNTIME_DIR.resolve()
    downloads_dir = (APP_VENDOR_DIR / "downloads").resolve()
    logs_dir = (APP_VENDOR_DIR / "logs").resolve()
    return {
        "root": APP_VENDOR_DIR.resolve(),
        "runtime": runtime_dir,
        "downloads": downloads_dir,
        "logs": logs_dir,
        "state_file": RUNTIME_STATE_FILE.resolve(),
    }


def ensure_runtime_dirs() -> dict[str, Path]:
    """创建在线安装版运行目录。"""

    dirs = get_runtime_dirs()
    for key in ("root", "runtime", "downloads", "logs"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    return dirs


def _get_manifest_candidates() -> list[Path]:
    """按优先级查找在线安装清单文件。"""

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / MANIFEST_FILE_NAME)
    candidates.append(Path(__file__).resolve().parent / MANIFEST_FILE_NAME)
    return candidates


def _load_manifest_from_file() -> RuntimeManifest | None:
    """从 JSON 文件加载在线安装清单。"""

    for candidate in _get_manifest_candidates():
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return RuntimeManifest(
            version=str(payload.get("version") or DEFAULT_RUNTIME_MANIFEST.version).strip(),
            package_url=str(payload.get("package_url") or "").strip(),
            package_sha256=str(payload.get("package_sha256") or "").strip().lower(),
            executable_name=str(payload.get("executable_name") or DEFAULT_EXECUTABLE_NAME).strip() or DEFAULT_EXECUTABLE_NAME,
        )
    return None


def _load_manifest_from_env() -> RuntimeManifest | None:
    """从环境变量加载在线安装清单覆盖项。"""

    package_url = os.environ.get("LOCAL_HELPER_ONLINE_PACKAGE_URL", "").strip()
    package_sha256 = os.environ.get("LOCAL_HELPER_ONLINE_PACKAGE_SHA256", "").strip().lower()
    version = os.environ.get("LOCAL_HELPER_ONLINE_RUNTIME_VERSION", "").strip()
    executable_name = os.environ.get("LOCAL_HELPER_ONLINE_EXECUTABLE", "").strip()

    if not any([package_url, package_sha256, version, executable_name]):
        return None

    return RuntimeManifest(
        version=version or DEFAULT_RUNTIME_MANIFEST.version,
        package_url=package_url,
        package_sha256=package_sha256,
        executable_name=executable_name or DEFAULT_EXECUTABLE_NAME,
    )


def load_runtime_manifest() -> RuntimeManifest:
    """加载运行时下载清单。"""

    env_manifest = _load_manifest_from_env()
    file_manifest = _load_manifest_from_file()
    base_manifest = file_manifest or DEFAULT_RUNTIME_MANIFEST

    if env_manifest is None:
        return base_manifest

    return RuntimeManifest(
        version=env_manifest.version or base_manifest.version,
        package_url=env_manifest.package_url or base_manifest.package_url,
        package_sha256=env_manifest.package_sha256 or base_manifest.package_sha256,
        executable_name=env_manifest.executable_name or base_manifest.executable_name,
    )


def read_installed_state() -> dict:
    """读取本地安装状态。"""

    state_file = get_runtime_dirs()["state_file"]
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_installed_state(payload: dict) -> None:
    """保存本地安装状态。"""

    state_file = ensure_runtime_dirs()["state_file"]
    state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_of_file(file_path: Path) -> str:
    """计算文件 SHA256。"""

    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_SIZE), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(file_path: Path, expected_sha256: str) -> None:
    """校验下载文件哈希。"""

    if not expected_sha256:
        return
    actual = sha256_of_file(file_path)
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"下载文件校验失败：{file_path.name}，期望 {expected_sha256.lower()}，实际 {actual.lower()}"
        )


def _download_local_file(source_url: str, destination: Path, callback: ProgressCallback = None) -> None:
    """支持使用 file:/// URL 做本地调试下载。"""

    parsed = urlparse(source_url)
    source_path = Path(parsed.path.lstrip("/")).resolve()
    if os.name == "nt" and parsed.netloc:
        source_path = Path(f"{parsed.netloc}{parsed.path}").resolve()
    if not source_path.exists():
        raise RuntimeError(f"本地安装包不存在：{source_path}")
    shutil.copy2(source_path, destination)
    _log(f"[install] 已从本地文件复制安装包：{source_path}", callback)


def download_to_file(source_url: str, destination: Path, expected_sha256: str, callback: ProgressCallback = None) -> None:
    """下载在线安装包到目标文件。"""

    if not source_url:
        raise RuntimeError(
            "在线安装版缺少 package_url。请先在 online_runtime_manifest.json "
            "或环境变量 LOCAL_HELPER_ONLINE_PACKAGE_URL 中配置完整下载地址。"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    _log("[install] 开始下载完整运行包...", callback)

    parsed = urlparse(source_url)
    if parsed.scheme == "file":
        _download_local_file(source_url, destination, callback)
    else:
        try:
            with requests.get(source_url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                response.raise_for_status()
                total_bytes = int(response.headers.get("Content-Length") or 0)
                downloaded_bytes = 0
                with destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded_bytes += len(chunk)
                        if total_bytes > 0:
                            percent = int(downloaded_bytes * 100 / total_bytes)
                            _log(f"[install] 运行包下载中：{percent}%", callback)
        except requests.RequestException as exc:
            raise RuntimeError(f"运行包下载失败：{exc}") from exc

    verify_sha256(destination, expected_sha256)
    _log(f"[install] 运行包下载完成：{destination}", callback)


def _resolve_extracted_runtime_root(extract_dir: Path, executable_name: str) -> Path:
    """从解压目录中识别真正的运行包根目录。"""

    direct_executable = extract_dir / executable_name
    if direct_executable.exists():
        return extract_dir

    nested_candidates = sorted(extract_dir.rglob(executable_name))
    if nested_candidates:
        return nested_candidates[0].parent

    raise RuntimeError(f"解压完成后未找到启动文件：{executable_name}")


def resolve_runtime_executable(manifest: RuntimeManifest) -> Path | None:
    """返回已安装运行包中的可执行文件路径。"""

    runtime_dirs = get_runtime_dirs()
    state = read_installed_state()
    if state.get("version") != manifest.version:
        return None
    executable_path = Path(str(state.get("executable_path") or "")).expanduser()
    if executable_path.exists():
        return executable_path.resolve()

    version_dir = (runtime_dirs["runtime"] / manifest.version).resolve()
    candidate = version_dir / manifest.executable_name
    if candidate.exists():
        return candidate.resolve()
    return None


def is_runtime_ready(manifest: RuntimeManifest) -> bool:
    """判断当前在线安装版运行时是否已经就绪。"""

    return resolve_runtime_executable(manifest) is not None


def install_runtime_package(manifest: RuntimeManifest, callback: ProgressCallback = None) -> Path:
    """下载并安装完整运行包。"""

    runtime_dirs = ensure_runtime_dirs()
    version_dir = (runtime_dirs["runtime"] / manifest.version).resolve()
    download_file = (runtime_dirs["downloads"] / f"{manifest.version}.zip").resolve()

    if download_file.exists():
        download_file.unlink()

    download_to_file(manifest.package_url, download_file, manifest.package_sha256, callback)

    temp_extract_dir = Path(tempfile.mkdtemp(prefix="local_helper_online_", dir=str(runtime_dirs["runtime"])))
    try:
        _log("[install] 正在解压完整运行包...", callback)
        with zipfile.ZipFile(download_file, "r") as archive:
            archive.extractall(temp_extract_dir)

        extracted_runtime_root = _resolve_extracted_runtime_root(temp_extract_dir, manifest.executable_name)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        version_dir.mkdir(parents=True, exist_ok=True)

        for item in extracted_runtime_root.iterdir():
            target = version_dir / item.name
            if item.is_dir():
                shutil.move(str(item), str(target))
            else:
                shutil.move(str(item), str(target))
    finally:
        if download_file.exists():
            download_file.unlink()
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)

    executable_path = (version_dir / manifest.executable_name).resolve()
    if not executable_path.exists():
        raise RuntimeError(f"安装完成后未找到启动文件：{executable_path}")

    write_installed_state(
        {
            "version": manifest.version,
            "executable_path": str(executable_path),
            "runtime_root": str(version_dir),
        }
    )
    _log(f"[install] 运行包安装完成：{version_dir}", callback)
    return executable_path


def ensure_online_runtime(callback: ProgressCallback = None) -> dict[str, str | bool]:
    """确保在线安装版运行包可用，并返回启动所需信息。"""

    manifest = load_runtime_manifest()
    executable_path = resolve_runtime_executable(manifest)
    installed_now = False

    if executable_path is None:
        _log("[install] 检测到首次运行，准备下载安装完整运行包。", callback)
        executable_path = install_runtime_package(manifest, callback)
        installed_now = True
    else:
        _log("[install] 检测到本地运行包已存在，直接启动。", callback)

    return {
        "runtime_root": str(executable_path.parent),
        "target_executable": str(executable_path),
        "logs_dir": str(get_runtime_dirs()["logs"]),
        "installed_now": installed_now,
    }
