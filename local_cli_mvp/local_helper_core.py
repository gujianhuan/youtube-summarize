"""
本地转写助手最小内核。

仅保留便携版分发真正需要的能力：
- 使用 yt-dlp 拉取视频音频
- 使用 faster-whisper 在本地 CPU 转写
- 可选将 transcript 上传到 bridge 并打开主站

刻意避免依赖大而全的 `core_logic.py`，防止 PyInstaller 把 OCR、
OpenAI、Torch、CUDA 等无关重依赖一并打包进去。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import requests

from portable_runtime import configure_portable_environment, get_models_dir, get_output_dir


configure_portable_environment()

DEFAULT_OUT_DIR = str(get_output_dir(create=True))
BRIDGE_HEALTH_TIMEOUT_SECONDS = 15
BRIDGE_UPLOAD_TIMEOUT_SECONDS = 20
BRIDGE_UPLOAD_RETRY_COUNT = 2
DEFAULT_MAIN_URL = "https://youtube-summarize-0oms.onrender.com/"
DEFAULT_BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com"
DEFAULT_BROWSER_COOKIE_ORDER = ("firefox", "edge", "chrome", "brave", "chromium")
TRANSCRIPT_SCHEMA_VERSION = "1.0"
BRIDGE_PAYLOAD_VERSION = 2

LogCallback = Callable[[str], None] | None


@dataclass
class LocalHelperConfig:
    """本地转写助手配置，供 CLI 与 GUI 共用。"""

    url: str
    out_dir: str = DEFAULT_OUT_DIR
    languages: str = "zh-Hans,zh,en"
    cookies_browser: str = "auto"
    cookies_file: str = ""
    timeout: float = 180.0
    retries: int = 1
    asr_model: str = "base"
    asr_force_cpu: bool = True
    push_to_main: bool = False
    main_url: str = DEFAULT_MAIN_URL
    bridge_api_url: str = DEFAULT_BRIDGE_API_URL
    bridge_api_token: str = ""
    no_open_browser: bool = False


def format_local_helper_error(exc: Exception) -> str:
    """格式化最小内核错误，返回适合 GUI 展示的短消息。"""

    message = str(exc or "").strip() or exc.__class__.__name__
    lowered = message.lower()
    if "cookiesfrombrowser" in lowered or "cookie" in lowered:
        return f"Cookie 读取失败：{message}"
    if "sign in to confirm" in lowered or "login" in lowered:
        return f"视频需要登录验证：{message}"
    if "ffmpeg" in lowered:
        return f"音频处理失败：{message}"
    if "bridge_" in lowered:
        return f"主站上传失败：{message}"
    if "yt-dlp" in lowered or "download" in lowered:
        return f"视频下载失败：{message}"
    return message


def safe_name(text: str) -> str:
    """生成适合作为文件名的安全字符串。"""

    value = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(text or "").strip())
    return value[:80] or "transcript"


def normalize_base_url(value: str) -> str:
    """标准化基础 URL。"""

    return str(value or "").strip().rstrip("/")


def build_main_url(main_url: str, payload_id: str, source_url: str) -> str:
    """构造主站自动拉取 transcript 的访问地址。"""

    normalized_main_url = str(main_url or "").strip() or DEFAULT_MAIN_URL
    query = {
        "ext_payload_id": payload_id,
        "ext_autosubmit": "1",
    }
    if source_url:
        query["ext_source_url"] = source_url
    joiner = "&" if "?" in normalized_main_url else "?"
    return f"{normalized_main_url}{joiner}{urlencode(query)}"


def build_local_transcript_envelope(
    request_id: str,
    transcript: str,
    source_url: str,
    title: str,
    video_id: str = "",
    language: str = "",
) -> dict:
    """构造本地工具上传用的 Transcript Envelope。"""

    clean_transcript = str(transcript or "").strip()
    clean_source_url = str(source_url or "").strip()
    clean_title = str(title or "").strip()
    clean_video_id = str(video_id or "").strip()
    clean_language = str(language or "").strip()
    return {
        "schemaVersion": TRANSCRIPT_SCHEMA_VERSION,
        "requestId": request_id,
        "source": {
            "kind": "local_tool",
            "sourceType": "local_asr",
            "toolVersion": "local-helper-minimal-core",
        },
        "video": {
            "platform": "youtube",
            "videoId": clean_video_id,
            "url": clean_source_url,
            "title": clean_title,
        },
        "transcript": {
            "language": clean_language,
            "text": clean_transcript,
            "segments": [],
            "charCount": len(clean_transcript),
        },
        "diagnostics": {
            "textSourceReason": "no_text_source_found",
            "fallbackUsed": True,
            "localHelperState": "uploading_bridge",
        },
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _log(log_callback: LogCallback, message: str) -> None:
    """安全写日志。"""

    if log_callback:
        log_callback(str(message))
    else:
        print(str(message))


def _resolve_cookie_sources(cookies_file: str, cookies_browser: str) -> list[dict[str, str]]:
    """解析 yt-dlp 可用的 Cookie 来源列表。"""

    sources: list[dict[str, str]] = []

    cookie_file_path = str(cookies_file or "").strip()
    if cookie_file_path:
        path = Path(cookie_file_path).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"Cookie 文件不存在：{path}")
        sources.append({"cookiefile": str(path)})

    browser_value = str(cookies_browser or "").strip().lower()
    if not browser_value:
        return sources

    if browser_value == "none":
        return sources

    browser_names: list[str]
    if browser_value == "auto":
        browser_names = [
            browser_name for browser_name in DEFAULT_BROWSER_COOKIE_ORDER if _is_browser_cookie_source_available(browser_name)
        ]
    else:
        browser_names = [part.strip() for part in browser_value.split(",") if part.strip()]

    for browser_name in browser_names:
        sources.append({"cookiesfrombrowser": browser_name})
    return sources


def _is_browser_cookie_source_available(browser_name: str) -> bool:
    """在 auto 模式下只探测本机真实可用的浏览器 Cookie 来源。"""

    name = str(browser_name or "").strip().lower()
    if not name:
        return False
    if os.name != "nt":
        return True

    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")

    def _has_chromium_cookie(base_dir: str) -> bool:
        if not base_dir or not os.path.isdir(base_dir):
            return False
        try:
            entries = os.listdir(base_dir)
        except OSError:
            return False
        profile_dirs = [entry for entry in entries if entry == "Default" or entry.startswith("Profile")]
        if not profile_dirs:
            profile_dirs = ["Default"]
        for profile_dir in profile_dirs:
            for candidate in ("Cookies", os.path.join("Network", "Cookies")):
                if os.path.exists(os.path.join(base_dir, profile_dir, candidate)):
                    return True
        return False

    if name == "chrome":
        return _has_chromium_cookie(os.path.join(local, "Google", "Chrome", "User Data"))
    if name == "edge":
        return _has_chromium_cookie(os.path.join(local, "Microsoft", "Edge", "User Data"))
    if name == "brave":
        return _has_chromium_cookie(os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"))
    if name == "chromium":
        return _has_chromium_cookie(os.path.join(local, "Chromium", "User Data"))
    if name == "firefox":
        profiles_dir = os.path.join(roaming, "Mozilla", "Firefox", "Profiles")
        if not os.path.isdir(profiles_dir):
            return False
        try:
            return any(os.path.exists(os.path.join(profiles_dir, entry, "cookies.sqlite")) for entry in os.listdir(profiles_dir))
        except OSError:
            return False
    return False


def _build_ydl_opts(
    outtmpl: str,
    timeout_seconds: float,
    retries: int,
    cookie_source: dict[str, str] | None,
    download: bool,
) -> dict:
    """构造 yt-dlp 配置。"""

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "socket_timeout": max(5.0, float(timeout_seconds)),
        "retries": max(0, int(retries)),
        "outtmpl": outtmpl,
        "paths": {"home": str(Path(outtmpl).parent)},
        "format": "bestaudio/best",
    }
    if not download:
        opts["skip_download"] = True
    if cookie_source:
        if "cookiefile" in cookie_source:
            opts["cookiefile"] = cookie_source["cookiefile"]
        elif "cookiesfrombrowser" in cookie_source:
            opts["cookiesfrombrowser"] = (cookie_source["cookiesfrombrowser"],)
    return opts


def _extract_video_info(url: str, config: LocalHelperConfig) -> tuple[dict, dict[str, str] | None]:
    """使用 yt-dlp 读取视频信息并记录成功的 Cookie 来源。"""

    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except Exception as exc:  # pragma: no cover - 依赖缺失时只在运行时触发
        raise RuntimeError("未安装 yt-dlp，无法下载视频。") from exc

    cookie_sources = _resolve_cookie_sources(config.cookies_file, config.cookies_browser)
    last_error: Exception | None = None
    attempts = cookie_sources or [None]

    for cookie_source in attempts:
        try:
            with YoutubeDL(_build_ydl_opts("%(id)s.%(ext)s", config.timeout, config.retries, cookie_source, False)) as ydl:
                info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise RuntimeError("yt-dlp 未返回有效的视频信息。")
            return info, cookie_source
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"yt-dlp 读取视频信息失败：{last_error}") from last_error


def _download_audio(
    url: str,
    config: LocalHelperConfig,
    temp_dir: Path,
    log_callback: LogCallback,
    cookie_source: dict[str, str] | None,
) -> tuple[Path, dict]:
    """下载最佳音频到临时目录。"""

    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except Exception as exc:  # pragma: no cover - 依赖缺失时只在运行时触发
        raise RuntimeError("未安装 yt-dlp，无法下载视频。") from exc

    outtmpl = str(temp_dir / "%(id)s.%(ext)s")
    _log(log_callback, "[status] 正在下载音频...")
    with YoutubeDL(_build_ydl_opts(outtmpl, config.timeout, config.retries, cookie_source, True)) as ydl:
        info = ydl.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp 下载后未返回有效信息。")
        downloaded_path = Path(ydl.prepare_filename(info))
        requested_downloads = info.get("requested_downloads") or []
        if requested_downloads and isinstance(requested_downloads, list):
            filepath = requested_downloads[0].get("filepath")
            if filepath:
                downloaded_path = Path(filepath)
        if not downloaded_path.exists():
            matches = sorted(temp_dir.glob("*"))
            file_candidates = [item for item in matches if item.is_file()]
            if not file_candidates:
                raise RuntimeError("音频下载完成，但未找到本地文件。")
            downloaded_path = file_candidates[0]
        return downloaded_path.resolve(), info


def _transcribe_audio(
    audio_path: Path,
    config: LocalHelperConfig,
    log_callback: LogCallback,
) -> str:
    """使用 faster-whisper 在 CPU 上执行本地转写。"""

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:  # pragma: no cover - 依赖缺失时只在运行时触发
        raise RuntimeError("未安装 faster-whisper，无法执行本地转写。") from exc

    model_name = (config.asr_model or "").strip() or "base"
    languages = [part.strip() for part in str(config.languages or "").split(",") if part.strip()]
    language = None if not languages or languages[0].lower() == "auto" else languages[0]
    model_root = str(get_models_dir(create=True))
    cpu_threads = max(1, min(os.cpu_count() or 4, 8))

    _log(log_callback, f"[status] 正在加载 Whisper 模型：{model_name}（CPU int8）...")
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
        download_root=model_root,
    )

    _log(log_callback, "[status] 正在执行本地转写...")
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
    )

    transcript_parts: list[str] = []
    segment_count = 0
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        transcript_parts.append(text)
        segment_count += 1
        if segment_count % 20 == 0:
            _log(log_callback, f"[status] 已完成 {segment_count} 个片段...")

    transcript = "\n".join(transcript_parts).strip()
    if not transcript:
        raise RuntimeError("转写结果为空，请检查视频音频是否可用。")

    detected_language = str(getattr(info, "language", "") or "unknown")
    _log(log_callback, f"[status] 转写完成，识别语言：{detected_language}，片段数：{segment_count}")
    return transcript


def wake_bridge_api(config: LocalHelperConfig, log_callback: LogCallback = None) -> bool:
    """预热 bridge 服务，降低冷启动超时概率。"""

    bridge_api_url = normalize_base_url(config.bridge_api_url)
    if not bridge_api_url:
        return False

    try:
        _log(log_callback, "[status] 正在唤醒 bridge 服务...")
        response = requests.get(
            f"{bridge_api_url}/health",
            timeout=BRIDGE_HEALTH_TIMEOUT_SECONDS,
            headers={"Cache-Control": "no-store"},
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def upload_bridge_payload_once(
    config: LocalHelperConfig,
    transcript: str,
    source_url: str,
    title: str = "",
    video_id: str = "",
) -> tuple[str, int]:
    """单次上传 transcript 到 bridge，返回 payload_id 和过期秒数。"""

    bridge_api_url = normalize_base_url(config.bridge_api_url)
    if not bridge_api_url:
        raise RuntimeError("bridge_api_url_missing")

    headers = {"Content-Type": "application/json"}
    if config.bridge_api_token.strip():
        headers["X-Bridge-Token"] = config.bridge_api_token.strip()

    payload_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    envelope = build_local_transcript_envelope(
        request_id=request_id,
        transcript=transcript,
        source_url=source_url,
        title=title,
        video_id=video_id,
    )
    payload = {
        "payloadId": payload_id,
        "transcript": transcript,
        "sourceUrl": source_url,
        "title": title,
        "bridgeVersion": BRIDGE_PAYLOAD_VERSION,
        "envelope": envelope,
    }

    try:
        response = requests.post(
            f"{bridge_api_url}/api/bridge/payload",
            headers=headers,
            json=payload,
            timeout=BRIDGE_UPLOAD_TIMEOUT_SECONDS,
        )
        result = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"bridge_request_failed:{type(exc).__name__}:{str(exc) or 'unknown'}") from exc
    except ValueError as exc:
        raise RuntimeError(f"bridge_invalid_json:http_{getattr(response, 'status_code', 'unknown')}") from exc

    if response.status_code != 200 or not isinstance(result, dict) or not result.get("ok"):
        error = str((result or {}).get("error") or f"http_{response.status_code}")
        raise RuntimeError(f"bridge_upload_failed:{error}")

    final_payload_id = str(result.get("payload_id") or payload_id).strip()
    expires_in = int(result.get("expires_in") or 0)
    if not final_payload_id:
        raise RuntimeError("bridge_payload_id_missing")
    return final_payload_id, expires_in


def upload_bridge_payload(
    config: LocalHelperConfig,
    transcript: str,
    source_url: str,
    title: str = "",
    video_id: str = "",
    log_callback: LogCallback = None,
) -> tuple[str, int]:
    """上传 transcript 到 bridge，包含预热与有限重试。"""

    wake_bridge_api(config, log_callback=log_callback)
    errors: list[str] = []

    for attempt in range(BRIDGE_UPLOAD_RETRY_COUNT):
        try:
            return upload_bridge_payload_once(config, transcript, source_url, title=title, video_id=video_id)
        except RuntimeError as exc:
            message = str(exc)
            errors.append(message)
            retryable = message.startswith("bridge_request_failed:")
            if not retryable or attempt >= BRIDGE_UPLOAD_RETRY_COUNT - 1:
                raise RuntimeError(" | ".join(errors)) from exc
            wake_bridge_api(config, log_callback=log_callback)

    raise RuntimeError(" | ".join(errors) or "bridge_upload_failed")


def run_local_helper(config: LocalHelperConfig, log_callback: LogCallback = None) -> dict:
    """执行本地转写助手主流程并返回结构化结果。"""

    out_dir = Path(config.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    _log(log_callback, "[status] 正在解析视频信息...")
    info, cookie_source = _extract_video_info(config.url, config)
    video_id = str(info.get("id") or "").strip()
    video_title = str(info.get("title") or video_id or "video").strip()
    video_url = str(info.get("webpage_url") or info.get("original_url") or config.url).strip()
    base_name = safe_name(video_id or video_title or "transcript")

    with tempfile.TemporaryDirectory(prefix="local_helper_") as temp_root:
        audio_path, info_after_download = _download_audio(
            url=config.url,
            config=config,
            temp_dir=Path(temp_root),
            log_callback=log_callback,
            cookie_source=cookie_source,
        )
        video_url = str(info_after_download.get("webpage_url") or video_url or config.url).strip()
        transcript = _transcribe_audio(audio_path, config, log_callback)

    transcript_path = out_dir / f"{base_name}.transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")
    _log(log_callback, f"[status] transcript 已保存：{transcript_path}")

    result_payload = {
        "ok": True,
        "video_id": video_id,
        "video_title": video_title,
        "video_url": video_url,
        "transcript_file": str(transcript_path),
        "transcript_chars": len(transcript),
        "mode": "minimal_local_core",
    }

    if config.push_to_main:
        try:
            payload_id, expires_in = upload_bridge_payload(
                config=config,
                transcript=transcript,
                source_url=video_url,
                title=video_title,
                video_id=video_id,
                log_callback=log_callback,
            )
            main_open_url = build_main_url(config.main_url, payload_id, video_url)
            result_payload["bridge_payload_id"] = payload_id
            result_payload["bridge_expires_in"] = expires_in
            result_payload["main_url"] = main_open_url
            result_payload["bridge_ok"] = True
            if config.no_open_browser:
                _log(log_callback, f"[status] bridge 上传完成，主站链接已生成：{main_open_url}")
            else:
                webbrowser.open(main_open_url)
                _log(log_callback, "[status] bridge 上传完成，已自动打开主站。")
        except Exception as exc:
            result_payload["bridge_ok"] = False
            result_payload["bridge_error"] = str(exc)
            _log(log_callback, f"[warn] bridge 上传失败：{exc}")
            _log(log_callback, f"[warn] transcript 已保存在本地，可稍后重试或手动粘贴：{transcript_path}")

    return result_payload


def result_to_json(payload: dict) -> str:
    """将执行结果序列化为 CLI 友好的 JSON。"""

    return json.dumps(payload, ensure_ascii=False, indent=2)
