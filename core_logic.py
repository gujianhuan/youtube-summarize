import time
import threading
import queue
import wave
import re
import os
import json
import sys
import glob
import tempfile
import shutil
import random
import hashlib
import base64
import subprocess
import traceback
import requests
import platform
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

from portable_runtime import configure_portable_environment, get_models_dir


configure_portable_environment()

def _configure_ffmpeg_path() -> str | None:
    """跨平台注册 imageio-ffmpeg 提供的二进制，兼容 Windows 和 Linux 部署环境。"""
    bundled_ffmpeg = str(os.environ.get("IMAGEIO_FFMPEG_EXE", "") or "").strip()
    if bundled_ffmpeg and os.path.exists(bundled_ffmpeg):
        ffmpeg_dir = os.path.dirname(bundled_ffmpeg)
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
            print(f"Added bundled ffmpeg to PATH: {ffmpeg_dir}")
        return bundled_ffmpeg

    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if not ffmpeg_path:
            return None

        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        target_ffmpeg = os.path.join(ffmpeg_dir, ffmpeg_name)

        if not os.path.exists(target_ffmpeg):
            try:
                shutil.copy2(ffmpeg_path, target_ffmpeg)
                if os.name != "nt":
                    os.chmod(target_ffmpeg, 0o755)
            except Exception as e:
                print(f"Failed to create ffmpeg alias {target_ffmpeg}: {e}")

        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
            print(f"Added ffmpeg to PATH: {ffmpeg_dir}")

        # 直接返回可执行文件路径，避免 Linux 环境误用 ffmpeg.exe 导致 yt-dlp 识别失败。
        return ffmpeg_path
    except ImportError:
        print("imageio-ffmpeg not found. Assuming ffmpeg is in PATH.")
        return None
    except Exception as e:
        print(f"Failed to auto-configure ffmpeg: {e}")
        return None


# 自动配置 ffmpeg 环境 (从 imageio-ffmpeg 获取)
ffmpeg_binary_path = _configure_ffmpeg_path()

from requests.adapters import HTTPAdapter
from urllib3 import Retry
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
)

# 自动配置 nodejs 环境
try:
    # 自动检测并添加 node.exe 到 PATH (仅本地 Windows 调试时可能用到)
    possible_node_paths = [
        r"d:\Program Files",
        r"D:\Program Files",
        r"C:\Program Files\nodejs",
        r"C:\Program Files (x86)\nodejs",
    ]
    for p in possible_node_paths:
        node_exe = os.path.join(p, "node.exe")
        if os.path.exists(node_exe):
            if p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                print(f"已自动添加 nodejs 到 PATH: {p}")
            break

except ImportError:
    print("未安装 imageio-ffmpeg，无法自动配置 ffmpeg 环境。")
except Exception as e:
    print(f"自动配置环境失败: {e}")


def resolve_cookie_file(
    cookies_file: str = "",
    cookies_content: str = "",
    cookies_content_b64: str = "",
) -> str:
    """
    解析可供 yt-dlp 使用的 cookies 文件路径。

    支持三种输入方式：
    1. 直接传入现成的 cookies 文件路径
    2. 传入 Netscape cookies 文本内容
    3. 传入 Base64 编码后的 cookies 文本
    """
    file_path = (cookies_file or "").strip()
    if file_path:
        return file_path

    raw_content = (cookies_content or "").strip()
    if not raw_content and (cookies_content_b64 or "").strip():
        try:
            raw_content = base64.b64decode(cookies_content_b64).decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"Cookies Base64 内容无效：{e}") from e

    if not raw_content:
        return ""

    runtime_dir = Path(tempfile.gettempdir()) / "youtube_summarizer_cookies"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:16]
    cookie_path = runtime_dir / f"cookies_{content_hash}.txt"
    if not cookie_path.exists():
        cookie_path.write_text(raw_content, encoding="utf-8")
    return str(cookie_path)


def build_cookie_runtime_diagnostics(
    api=None,
    *,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    resolved_cookie_file: str = "",
    resolve_error: str = "",
) -> str:
    """
    生成 cookies 运行时诊断信息。

    只输出来源、长度、文件存在性等元数据，不泄露真实 cookie 内容。
    """
    raw_file = str(cookies_file or getattr(api, "_cookies_file", "") or "").strip()
    raw_content = str(getattr(api, "_cookies_content", "") or "").strip()
    raw_b64 = str(getattr(api, "_cookies_content_b64", "") or "").strip()
    browser = str(cookies_from_browser or getattr(api, "_cookies_from_browser", "") or "").strip().lower()

    parts = [
        f"input_file={'yes' if raw_file else 'no'}",
        f"input_content={'yes' if raw_content else 'no'}",
        f"input_b64={'yes' if raw_b64 else 'no'}",
        f"browser={browser or 'none'}",
    ]
    if raw_b64:
        parts.append(f"b64_len={len(raw_b64)}")
    if resolve_error:
        parts.append(f"resolve_error={resolve_error}")

    resolved_path = str(resolved_cookie_file or "").strip()
    if resolved_path:
        try:
            cookie_path = Path(resolved_path)
            exists = cookie_path.exists()
            parts.append(f"resolved_file={'yes' if exists else 'no'}")
            parts.append(f"resolved_name={cookie_path.name}")
            if exists:
                parts.append(f"resolved_size={cookie_path.stat().st_size}")
                first_line = cookie_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                first_line_text = first_line[0].strip() if first_line else ""
                parts.append(f"netscape_header={'yes' if first_line_text.startswith('# Netscape HTTP Cookie File') else 'no'}")
        except Exception as e:
            parts.append(f"resolved_check_error={type(e).__name__}:{e}")
    else:
        parts.append("resolved_file=no")

    return "; ".join(parts)


def build_runtime_version_diagnostics() -> str:
    """输出当前运行实例的版本信息，便于确认 Render 是否部署到最新提交。"""
    render_commit = str(os.environ.get("RENDER_GIT_COMMIT", "") or "").strip()
    render_service = str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip()
    render_instance = str(os.environ.get("RENDER_INSTANCE_ID", "") or "").strip()
    app_expected_commit = "latest-local"
    parts = [f"expected_commit={app_expected_commit}"]
    parts.append(f"render_commit={render_commit or 'unknown'}")
    parts.append(f"render_service={'set' if render_service else 'unknown'}")
    parts.append(f"render_instance={'set' if render_instance else 'unknown'}")
    return "; ".join(parts)


def get_remote_worker_status(timeout_seconds: float = 4.0) -> dict:
    """检查远程抓取节点配置、健康状态和 Render ASR 兜底策略。"""
    remote_enabled = str(
        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"
    ).strip().lower() in {"1", "true", "yes"}
    worker_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
    remote_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()
    worker_token = str(os.environ.get("REMOTE_TRANSCRIBE_TOKEN", "") or "").strip()
    running_on_render = bool(str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip())
    disable_render_asr_fallback = running_on_render and str(
        os.environ.get("REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK", "0") or "0"
    ).strip().lower() not in {"0", "false", "no"}

    status = {
        "configured": remote_enabled and bool(worker_url),
        "remote_enabled": remote_enabled,
        "remote_mode": remote_mode if remote_enabled else "disabled",
        "worker_url": worker_url,
        "worker_host": "",
        "worker_health_url": "",
        "worker_token_configured": bool(worker_token),
        "running_on_render": running_on_render,
        "disable_render_asr_fallback": disable_render_asr_fallback,
        "health_ok": False,
        "health_status_code": None,
        "health_error": "",
        "health_payload": {},
    }

    if not remote_enabled:
        status["health_error"] = "REMOTE_TRANSCRIBE_ENABLED=0"
        return status

    if not worker_url:
        status["health_error"] = "未配置 REMOTE_TRANSCRIBE_URL"
        return status

    parsed = urlparse(worker_url)
    base = worker_url.rsplit("/fetch-transcript", 1)[0] if "/fetch-transcript" in worker_url else worker_url.rstrip("/")
    health_url = f"{base}/health"
    status["worker_host"] = parsed.netloc or worker_url
    status["worker_health_url"] = health_url

    try:
        resp = requests.get(health_url, timeout=max(1.0, float(timeout_seconds)), verify=False)
        status["health_status_code"] = resp.status_code
        if resp.ok:
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw_text": resp.text[:500]}
            status["health_payload"] = payload if isinstance(payload, dict) else {"raw": payload}
            status["health_ok"] = bool(status["health_payload"].get("ok", True))
            if not status["health_ok"]:
                status["health_error"] = str(status["health_payload"].get("error") or "健康检查返回 ok=false")
        else:
            status["health_error"] = f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        status["health_error"] = f"{type(e).__name__}: {e}"

    return status


def try_fetch_transcript_via_remote_worker(
    video_id: str,
    video_url: str,
    languages: list[str],
    api=None,
) -> str:
    """
    通过外部抓取节点拉取 transcript 文本。

    仅返回 transcript 文本，不负责总结。
    """
    remote_enabled = str(
        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"
    ).strip().lower() in {"1", "true", "yes"}
    if not remote_enabled:
        raise RuntimeError("远程抓取节点已禁用（REMOTE_TRANSCRIBE_ENABLED=0）")

    worker_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
    worker_token = str(os.environ.get("REMOTE_TRANSCRIBE_TOKEN", "") or "").strip()
    if not worker_url:
        raise RuntimeError("未配置 REMOTE_TRANSCRIBE_URL")

    timeout_seconds = float(getattr(api, "_timeout_seconds", 60.0) or 60.0) if api else 60.0
    worker_timeout_seconds = float(os.environ.get("REMOTE_TRANSCRIBE_TIMEOUT_SECONDS", "180") or "180")
    processing_extension_seconds = float(os.environ.get("REMOTE_TRANSCRIBE_PROCESSING_EXTENSION_SECONDS", "240") or "240")
    poll_interval_seconds = float(os.environ.get("REMOTE_TRANSCRIBE_POLL_INTERVAL_SECONDS", "2.0") or "2.0")
    payload = {
        "video_id": video_id,
        "video_url": video_url,
        "languages": list(languages or []),
        "cookies_file": str(getattr(api, "_cookies_file", "") or "").strip() if api else "",
        "cookies_content": str(getattr(api, "_cookies_content", "") or "") if api else "",
        "cookies_content_b64": str(getattr(api, "_cookies_content_b64", "") or "").strip() if api else "",
        "cookies_from_browser": str(getattr(api, "_cookies_from_browser", "") or "").strip().lower() if api else "",
        "asr_enabled": bool(getattr(api, "_asr_enabled", False)) if api else False,
        "asr_model": str(getattr(api, "_asr_model", "") or "") if api else "",
        "asr_language": str(getattr(api, "_asr_language", "") or "") if api else "",
        "asr_fast_mode": bool(getattr(api, "_asr_fast_mode", False)) if api else False,
        "asr_force_cpu": bool(getattr(api, "_asr_force_cpu", False)) if api else False,
    }
    headers = {"Content-Type": "application/json"}
    if worker_token:
        headers["X-Worker-Token"] = worker_token

    def _raise_remote_connectivity_error(exc: Exception) -> None:
        host = urlparse(worker_url).netloc or worker_url
        detail = f"{type(exc).__name__}: {exc}"
        if "trycloudflare.com" in host:
            raise RuntimeError(
                "本地抓取节点不可达：当前配置的是临时 Cloudflare Tunnel 地址，且该地址已失效或无法解析。"
                f" host={host}；detail={detail}。"
                " 请在本地重启 `cloudflared tunnel --url http://127.0.0.1:8787`，"
                "拿到新的 trycloudflare 地址后，立即更新 Render 的 `REMOTE_TRANSCRIBE_URL`。"
                " 如果需要给朋友持续测试，建议改用固定域名的 Cloudflare Tunnel、Tailscale Funnel 或 ngrok。"
            )
        raise RuntimeError(
            f"本地抓取节点不可达：host={host}；detail={detail}。"
            " 请检查本地抓取节点、隧道进程以及 Render 中的 `REMOTE_TRANSCRIBE_URL` 是否仍然有效。"
        )

    try:
        submit_resp = requests.post(
            worker_url,
            headers=headers,
            json=payload,
            timeout=(10.0, 20.0),
        )
    except requests.exceptions.ConnectionError as e:
        _raise_remote_connectivity_error(e)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"提交本地抓取任务失败：{type(e).__name__}: {e}")
    if submit_resp.status_code == 401:
        raise RuntimeError(
            "本地抓取节点拒绝了请求（401 Unauthorized）。"
            " 这通常表示 Render 端的 `REMOTE_TRANSCRIBE_TOKEN` 与本地抓取节点的 `REMOTE_TRANSCRIBE_TOKEN` 不一致，"
            "或本地节点要求 token 但 Render 未正确携带。"
        )
    submit_resp.raise_for_status()
    data = submit_resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("本地抓取节点返回格式无效")
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "本地抓取节点执行失败"))
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        transcript_text = str(data.get("transcript_text") or "").strip()
        transcript_label = str(data.get("transcript_label") or "remote-worker").strip()
        if not transcript_text:
            raise RuntimeError("本地抓取节点未返回 transcript 文本")
        return f"[{transcript_label}]\n\n{transcript_text}"

    status_base = worker_url.rsplit("/fetch-transcript", 1)[0]
    status_url = f"{status_base}/task/{quote(task_id)}"
    deadline = time.monotonic() + max(30.0, timeout_seconds, worker_timeout_seconds)
    last_stage = ""
    last_stage_detail = ""
    last_status = ""
    processing_deadline_extended = False

    while time.monotonic() < deadline:
        time.sleep(max(0.5, poll_interval_seconds))
        try:
            poll_resp = requests.get(status_url, headers=headers, timeout=(10.0, 20.0))
        except requests.exceptions.ConnectionError as e:
            _raise_remote_connectivity_error(e)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"查询本地抓取节点状态失败：{type(e).__name__}: {e}")
        if poll_resp.status_code == 401:
            raise RuntimeError(
                "查询本地抓取节点状态被拒绝（401 Unauthorized）。"
                " 请检查 Render 端与本地节点的 `REMOTE_TRANSCRIBE_TOKEN` 是否完全一致。"
            )
        poll_resp.raise_for_status()
        poll_data = poll_resp.json()
        if not isinstance(poll_data, dict) or not poll_data.get("ok"):
            raise RuntimeError("本地抓取节点状态查询失败")
        status = str(poll_data.get("status") or "").strip().lower()
        last_status = status
        last_stage = str(poll_data.get("stage") or "").strip()
        last_stage_detail = str(poll_data.get("stage_detail") or "").strip()
        if (
            not processing_deadline_extended
            and status in {"queued", "running"}
            and last_stage == "processing"
            and any(token in last_stage_detail.lower() for token in ["whisper", "转写", "audio", "音频"])
        ):
            deadline = max(deadline, time.monotonic() + max(60.0, processing_extension_seconds))
            processing_deadline_extended = True
        if status in {"queued", "running"}:
            continue
        if status == "failed":
            raise RuntimeError(str(poll_data.get("error") or "本地抓取节点执行失败"))
        if status == "success":
            transcript_text = str(poll_data.get("transcript_text") or "").strip()
            transcript_label = str(poll_data.get("transcript_label") or "remote-worker").strip()
            if not transcript_text:
                raise RuntimeError("本地抓取节点未返回 transcript 文本")
            return f"[{transcript_label}]\n\n{transcript_text}"
        raise RuntimeError(f"本地抓取节点返回未知状态: {status or 'unknown'}")

    timeout_hint = f"本地抓取节点处理超时（>{int(max(30.0, timeout_seconds, worker_timeout_seconds))}s）"
    if last_status or last_stage or last_stage_detail:
        timeout_hint += (
            f"；last_status={last_status or 'unknown'}"
            f"；stage={last_stage or 'unknown'}"
            f"；detail={last_stage_detail or 'none'}"
        )
    raise RuntimeError(timeout_hint)


class TimeoutSession(requests.Session):
    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.verify = False  # 全局禁用 SSL 验证，解决代理证书问题
        self._timeout_seconds = timeout_seconds
        self._exception_retries = 2
        self._deadline_s: float | None = None
        self.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Encoding": "identity",
            }
        )

    def request(self, method, url, **kwargs):
        if self._deadline_s is not None and time.monotonic() > self._deadline_s:
            raise requests.exceptions.Timeout("已超过整体超时时间")
        if "timeout" not in kwargs:
            kwargs["timeout"] = (min(10.0, self._timeout_seconds), self._timeout_seconds)
        last_exc: Exception | None = None
        retries = max(0, int(getattr(self, "_exception_retries", 0)))
        for attempt in range(retries + 1):
            try:
                return super().request(method, url, **kwargs)
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(0.6 * (2**attempt))
        assert last_exc is not None
        raise last_exc


def _strip_trailing_punct(text: str) -> str:
    return re.sub(r"[!！。,.，?？;；:：\)\]）】]+$", "", text or "")


def extract_video_id(url_or_id: str) -> str:
    candidate = _strip_trailing_punct(url_or_id.strip())
    
    # Bilibili BV ID (BV1xxxxxxxxx) - 12 chars usually, starts with BV
    if re.fullmatch(r"BV[a-zA-Z0-9]{10}", candidate):
        return candidate
        
    # Bilibili URL
    if "bilibili.com" in candidate:
        # Match BV id in url
        m = re.search(r"(BV[a-zA-Z0-9]{10})", candidate)
        if m:
            return m.group(1)
            
    # YouTube ID (11 chars)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate) and (
        candidate.startswith("www.") or "youtube.com" in candidate or "youtu.be" in candidate
    ):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()

    if "youtu.be" in host:
        video_id = _strip_trailing_punct(parsed.path.strip("/").split("/")[0])
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id

    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            video_id = _strip_trailing_punct(qs["v"][0])
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id

        m = re.search(r"/(shorts|embed)/([A-Za-z0-9_-]{11})", parsed.path)
        if m:
            return m.group(2)

    raise ValueError("无法从输入解析出视频 ID（支持 YouTube 11位 ID / Bilibili BV号）")


def normalize_video_url(url_or_id: str) -> str:
    s = _strip_trailing_punct(url_or_id.strip())
    
    # Bilibili
    if re.fullmatch(r"BV[a-zA-Z0-9]{10}", s) or "bilibili.com" in s:
        if not s.startswith("http"):
             if re.fullmatch(r"BV[a-zA-Z0-9]{10}", s):
                 return f"https://www.bilibili.com/video/{s}"
             return "https://" + s
        return s

    # YouTube
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return f"https://www.youtube.com/watch?v={s}"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s) and (
        s.startswith("www.") or "youtube.com" in s or "youtu.be" in s
    ):
        s = "https://" + s
    return s


class CookieManager:
    """集中管理 Cookie 的获取、验证与错误处理"""
    
    @staticmethod
    def is_cookie_error(msg: str | Exception) -> bool:
        """统一识别 yt-dlp 报告的 Cookie 相关错误"""
        s = strip_ansi(str(msg or "")).lower()
        # 使用正则进行更鲁棒的匹配
        patterns = [
            r"could not copy.*cookie", # 数据库被锁定
            r"cookie database",
            r"database is locked",
            r"permission denied.*cookie",
            r"access is denied",
            r"used by another process",
            r"winerror 32", # 文件占用
            r"winerror 5",  # 拒绝访问
            r"sqlite3.*locked",
            r"dpapi.*decrypt",
            r"dpapi.*failed",
            r"unable to extract.*cookie",
        ]
        return any(re.search(p, s) for p in patterns)

    @staticmethod
    def get_fatal_msg(err_msg: str, browser: str) -> str:
        """生成统一且带有具体指引的致命 Cookie 错误信息"""
        browser_name = browser or "浏览器"
        details_raw = strip_ansi(err_msg).replace("ERROR: ", "").strip()
        detail_lines = [x.strip() for x in re.split(r"[\r\n]+", details_raw) if x and x.strip()]
        detail_seen: set[str] = set()
        detail_dedup: list[str] = []
        for x in detail_lines:
            k = x.lower()
            if k in detail_seen:
                continue
            detail_seen.add(k)
            detail_dedup.append(x)
        details = " | ".join(detail_dedup) if detail_dedup else details_raw
        d_lower = details.lower()
        
        # 1. 针对新版 Chromium 的解密限制 (DPAPI)
        if "dpapi" in d_lower:
            return (
                f"❌ 浏览器 Cookie 解密失败 (DPAPI Error)。\n"
                f"原因：{browser_name} (新版基于 Chromium 127+) 引入了增强加密，外部程序已无法直接解密 Cookie。\n\n"
                f"💡 解决方法：\n"
                f"1. **使用 Firefox**：Firefox 暂不受此限制影响，请在 Firefox 中登录 YouTube 后，在设置中将浏览器改为 firefox (或 auto)。\n"
                f"2. **手动导出 Cookie**：安装浏览器插件（如 'Get cookies.txt LOCALLY'）导出 cookies.txt，并在设置中提供文件路径。\n\n"
                f"原始细节: {details}"
            )
            
        # 2. 针对数据库锁定/无法复制 (常见于浏览器未彻底关闭)
        if any(x in d_lower for x in ["locked", "another process", "could not copy", "32"]):
             return (
                f"❌ 浏览器 Cookie 数据库被锁定或无法访问。\n"
                f"原因：{browser_name} 正在运行或其数据库文件被占用。\n\n"
                f"💡 解决方法：\n"
                f"1. **彻底关闭浏览器**：请确保所有 {browser_name} 窗口已关闭（包括后台进程），然后重试。\n"
                f"2. **使用 Firefox 或导出 Cookie**：参考上述方案。\n\n"
                f"原始细节: {details}"
            )
        
        return f"❌ 无法从 {browser_name} 获取 Cookie。\n细节: {details}"

    @staticmethod
    def get_sources(cookies_file: str, cookies_from_browser: str, force_browser_cookie: bool = False) -> list[tuple[str, str]]:
        """返回 (cookiefile, browser) 元组列表，支持智能回退"""
        file_path = (cookies_file or "").strip()
        browser_name = (cookies_from_browser or "").strip().lower()
        
        sources: list[tuple[str, str]] = []
        if file_path:
            # 只要上层已提供 cookies 文件路径，就优先尝试文件模式。
            # 不在这里强依赖 exists 判断，避免云端时序/挂载差异导致错误退化为 cookie=none。
            sources.append((file_path, ""))
            return sources
        
        # 确定浏览器候选列表
        candidates = []
        if browser_name and browser_name != "auto":
            candidates = [browser_name]
            # 后备方案：如果显式指定了容易受限的 Chromium，则将 firefox 作为最后保单
            if browser_name in ["chrome", "edge", "brave", "chromium"] and "firefox" not in candidates:
                candidates.append("firefox")
        else:
            # 自动模式或默认：Firefox 优先级最高（最稳），其次是主流 Chromium
            candidates = ["firefox", "edge", "chrome", "brave", "chromium"]

        for b in candidates:
            if CookieManager.is_browser_available(b):
                sources.append(("", b))
        
        if not sources and force_browser_cookie:
            sources.append(("", "chrome"))
        if ("", "") not in sources:
            sources.append(("", ""))
            
        return sources

    @staticmethod
    def is_browser_available(browser: str) -> bool:
        """检测系统中是否安装了指定浏览器并存在 Cookie 数据库"""
        b = (browser or "").strip().lower()
        if not b: return False
        if os.name != "nt": return True # 非 Windows 暂不严格检查路径
        
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        
        def has_chromium_cookie(base_dir: str) -> bool:
            if not base_dir or not os.path.isdir(base_dir): return False
            try:
                # 检查 Default 或 Profile x 目录
                entries = os.listdir(base_dir)
                profile_dirs = [d for d in entries if d == "Default" or d.startswith("Profile")]
                if not profile_dirs: profile_dirs = ["Default"]
                for d in profile_dirs:
                    if os.path.exists(os.path.join(base_dir, d, "Cookies")): return True
                    if os.path.exists(os.path.join(base_dir, d, "Network", "Cookies")): return True
            except: pass
            return False

        if b == "chrome":
            return has_chromium_cookie(os.path.join(local, "Google/Chrome/User Data"))
        if b == "edge":
            return has_chromium_cookie(os.path.join(local, "Microsoft/Edge/User Data"))
        if b == "brave":
            return has_chromium_cookie(os.path.join(local, "BraveSoftware/Brave-Browser/User Data"))
        if b == "chromium":
            return has_chromium_cookie(os.path.join(local, "Chromium/User Data"))
        if b == "firefox":
            # 检查 Roaming 下的 Profiles
            base = os.path.join(roaming, "Mozilla/Firefox/Profiles")
            if os.path.isdir(base):
                try:
                    for name in os.listdir(base):
                        if os.path.exists(os.path.join(base, name, "cookies.sqlite")): return True
                except: pass
            return False
        return False




def expand_languages(languages: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        x = x.strip()
        if not x or x in seen:
            return
        seen.add(x)
        out.append(x)

    for lang in languages:
        add(lang)
        if lang == "zh-Hans":
            add("zh-Hant")
            add("zh")
            add("zh-CN")
            add("zh-TW")
        elif lang == "zh-Hant":
            add("zh-Hans")
            add("zh")
            add("zh-TW")
            add("zh-CN")
        elif lang == "zh":
            add("zh-Hans")
            add("zh-Hant")
            add("zh-CN")
            add("zh-TW")
        elif lang.lower() == "en":
            add("en-US")
            add("en-GB")

    return out


def detect_windows_proxy() -> tuple[str, str]:
    # 1. 尝试从注册表读取
    try:
        import winreg  # type: ignore
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            proxy_enable = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
            auto_config_url = str(winreg.QueryValueEx(key, "AutoConfigURL")[0] or "")
        
        if auto_config_url:
            return "", f"检测到 PAC: {auto_config_url}"

        if proxy_enable == 1 and proxy_server:
            server = proxy_server.strip()
            if ";" in server or "=" in server:
                parts = [p.strip() for p in server.split(";") if p.strip()]
                mapping: dict[str, str] = {}
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        mapping[k.strip().lower()] = v.strip()
                    else:
                        mapping["http"] = p
                        mapping["https"] = p
                candidate = mapping.get("https") or mapping.get("http") or ""
                if candidate:
                    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
                        candidate = "http://" + candidate
                    return candidate, ""
            else:
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", server):
                    server = "http://" + server
                return server, ""
    except Exception:
        pass

    # 2. 尝试常见代理端口兜底检测
    common_ports = [7890, 7897, 10809, 1080, 8080]
    for port in common_ports:
        candidate = f"http://127.0.0.1:{port}"
        try:
            # 快速检测端口是否开放
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return candidate, f"自动扫描到本地代理: {candidate}"
        except Exception:
            continue

    return "", ""


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", s)

def has_js_challenge_failure(lines: list[str]) -> bool:
    tail = "\n".join(lines[-120:]).lower()
    return (
        "challenge solving failed" in tail
        or "error solving n challenge" in tail
        or "only images are available" in tail
    )

def has_po_token_required(lines: list[str]) -> bool:
    tail = "\n".join(lines[-160:]).lower()
    return (
        ("po token" in tail and "required" in tail)
        or ("po token" in tail and "not provided" in tail)
        or ("po token" in tail and "skipped" in tail)
        or ("gvs po token" in tail)
    )


def detect_js_runtime() -> tuple[bool, str]:
    runtimes = []
    for name in ("node", "deno", "bun", "quickjs", "qjs"):
        if shutil.which(name):
            runtimes.append(name)
    return bool(runtimes), ",".join(runtimes) if runtimes else "none"

def has_login_required(lines: list[str], msg: str = "") -> bool:
    tail = "\n".join(lines[-160:]).lower()
    m = (msg or "").lower()
    return (
        "login_required" in tail
        or "sign in to confirm you’re not a bot" in tail
        or "sign in to confirm you're not a bot" in tail
        or "use --cookies-from-browser" in tail
        or "use --cookies" in tail
        or "login_required" in m
        or "sign in to confirm you’re not a bot" in m
        or "sign in to confirm you're not a bot" in m
        or "use --cookies-from-browser" in m
        or "use --cookies" in m
    )


def has_premium_only_warning(lines: list[str], msg: str = "") -> bool:
    tail = "\n".join(lines[-160:]).lower()
    m = (msg or "").lower()
    premium_markers = [
        "become a premium member",
        "formats) 1080p",
        "formats are missing",
        "format(s)",
        "高码率 are missing",
        "高码率",
    ]
    combined = tail + "\n" + m
    return any(marker in combined for marker in premium_markers)

def is_html_like_text(text: str | None) -> bool:
    if not text:
        return False
    sample = text.strip().lower()
    if sample.startswith("<!doctype") or sample.startswith("<html"):
        return True
    if "<html" in sample[:2000]:
        return True
    head_idx = sample.find("<head")
    body_idx = sample.find("<body")
    if head_idx != -1 and body_idx != -1 and abs(head_idx - body_idx) < 5000:
        return True
    return False

def _audio_cache_root() -> Path | None:
    try:
        root = Path(__file__).resolve().parent / ".cache" / "audio"
        root.mkdir(parents=True, exist_ok=True)
        return root
    except Exception:
        return None

def _audio_cache_key(video_url: str) -> str:
    try:
        vid = extract_video_id(video_url)
        if vid:
            return vid
    except Exception:
        pass
    h = hashlib.sha1(video_url.encode("utf-8", errors="ignore")).hexdigest()
    return h

def _audio_cache_path(video_url: str) -> Path | None:
    root = _audio_cache_root()
    if not root:
        return None
    key = _audio_cache_key(video_url)
    return root / f"{key}.wav"


def get_effective_proxy(proxy_url: str, use_system_proxy: bool) -> tuple[str, str]:
    proxy_url = (proxy_url or "").strip()
    if proxy_url:
        return proxy_url, ""
    if use_system_proxy:
        return detect_windows_proxy()
    return "", ""


def is_fatal_network_error(msg: str) -> bool:
    """
    检测是否为不可恢复的全局网络错误（代理失效、连接拒绝、DNS 解析失败等）。
    出现此类错误时，继续轮换客户端/Cookie 策略毫无意义，应立即中断所有重试。
    """
    s = str(msg or "").lower()
    return any([
        "proxyerror" in s,
        "proxy error" in s,
        "cannot connect to proxy" in s,
        "tunnel connection failed" in s,
        "failed to establish a new connection" in s,
        "name or service not known" in s,
        "getaddrinfo failed" in s,
        "nodename nor servname provided" in s,
        "connection refused" in s,
        "connection reset by peer" in s,
        "network is unreachable" in s,
        "no route to host" in s,
        # 整体超时（不同于单次请求超时）
        "已超过整体超时时间" in s,
        "timed out" in s and ("connect" in s or "proxy" in s),
    ])



def build_api(proxy_url: str, timeout_seconds: float, use_system_proxy: bool, retries: int) -> YouTubeTranscriptApi:
    session = TimeoutSession(timeout_seconds=max(1.0, float(timeout_seconds)))
    session.trust_env = True
    effective_proxy, pac_note = get_effective_proxy(proxy_url, use_system_proxy)
    if effective_proxy:
        session.trust_env = False
        session.proxies = {"http": effective_proxy, "https": effective_proxy}
    session._deadline_s = time.monotonic() + max(2.0, float(timeout_seconds))  # type: ignore[attr-defined]
    retry_cfg = Retry(total=max(0, int(retries)), backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry_cfg)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session._exception_retries = max(1, int(retries))
    api = YouTubeTranscriptApi(http_client=session)
    api._pac_note = pac_note  # type: ignore[attr-defined]
    api._effective_proxy = effective_proxy  # type: ignore[attr-defined]
    api._timeout_seconds = float(timeout_seconds)  # type: ignore[attr-defined]
    api._retries = int(retries)  # type: ignore[attr-defined]
    return api


def vtt_to_text(vtt: str) -> str:
    lines: list[str] = []
    for raw in vtt.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("WEBVTT"):
            continue
        if "-->" in s:
            continue
        if s.isdigit():
            continue
        if s.startswith("NOTE"):
            continue
        lines.append(s)

    out: list[str] = []
    prev = None
    for s in lines:
        if s == prev:
            continue
        out.append(s)
        prev = s
    return "\n".join(out)


def fetch_subtitles_with_ytdlp(
    video_url: str,
    preferred_langs: list[str],
    proxy_url: str,
    timeout_seconds: float,
    retries: int,
    cookies_file: str,
    cookies_from_browser: str,
) -> tuple[str, str]:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
        from yt_dlp.utils import DownloadError  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "未安装 yt-dlp，无法启用兜底抓取。可执行：python -m pip install yt-dlp -i https://pypi.tuna.tsinghua.edu.cn/simple"
        ) from e

    # 移除 detect_js_runtime 的定义，改用 yt-dlp 原生解释器或 yt_dlp_ejs
    langs = preferred_langs[:] if preferred_langs else []
    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        last_err: Exception | None = None
        last_cookie_error: RuntimeError | None = None
        disabled_browsers: set[str] = set()
        last_video_id = ""
        disabled_web = False
        force_browser_cookie = False

        import random

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        ]

        class YdlLogger:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def _add(self, level: str, msg: str) -> None:
                s = strip_ansi(str(msg or "")).strip()
                if not s:
                    return
                self.lines.append(f"[{level}] {s}")
                if len(self.lines) > 400:
                    self.lines = self.lines[-250:]

            def debug(self, msg: str) -> None:
                self._add("debug", msg)

            def info(self, msg: str) -> None:
                self._add("info", msg)

            def warning(self, msg: str) -> None:
                self._add("warning", msg)

            def error(self, msg: str) -> None:
                self._add("error", msg)

        def extract_info_with_format_rotation(ydl_opts: dict) -> dict:
            format_candidates = [None, "bestaudio/best", "worstaudio/worst"]
            last_format_err: Exception | None = None
            for fmt in format_candidates:
                if fmt:
                    ydl_opts["format"] = fmt
                else:
                    ydl_opts.pop("format", None)
                try:
                    with YoutubeDL(ydl_opts) as ydl:
                        return ydl.extract_info(video_url, download=False, process=False)
                except DownloadError as e:
                    msg = strip_ansi(str(e))
                    if "Requested format is not available" in msg:
                        last_format_err = e
                        continue
                    raise
            if last_format_err is not None:
                raise last_format_err
            return {}

        # 移除此处的本地 is_cookie_error 定义，改用顶层的 _is_cookie_error

        def build_download_session() -> requests.Session:
            sess = TimeoutSession(timeout_seconds=max(1.0, float(timeout_seconds)))
            sess.trust_env = True
            if proxy_url:
                sess.trust_env = False
                sess.proxies = {"http": proxy_url, "https": proxy_url}
            sess._deadline_s = time.monotonic() + max(2.0, float(timeout_seconds))  # type: ignore[attr-defined]
            retry_cfg = Retry(
                total=max(0, int(retries)),
                backoff_factor=0.8,
                status_forcelist=[500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_cfg)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            sess._exception_retries = max(1, int(retries))
            return sess

        def maybe_force_vtt(url: str) -> str:
            if "timedtext" not in url:
                return url
            if "fmt=" in url:
                return url
            return url + ("&" if "?" in url else "?") + "fmt=vtt"

        def try_extract_and_download_by_url() -> tuple[str, str] | None:
            nonlocal force_browser_cookie, last_cookie_error, disabled_browsers
            sess = build_download_session()
            client_sets: list[list[str]] = [["android"], ["ios"], ["web_safari"], ["web"], ["tv"]]
            attempt_retries = max(1, int(retries))
            
            # 用于记录 "无 Cookie" 模式下的错误
            no_cookie_error: Exception | None = None
            
            for client_set in client_sets:
                if disabled_web and "web" in client_set:
                    continue
                for attempt in range(attempt_retries):
                    ua = random.choice(user_agents)
                    for cookiefile, cfb in CookieManager.get_sources(cookies_file, cookies_from_browser, force_browser_cookie):
                        if cfb and cfb in disabled_browsers:
                            continue
                        info = None
                        logger = YdlLogger()
                        opts: dict = {
                            "skip_download": True,
                            "quiet": True,
                            "no_warnings": True,
                            "verbose": True,
                            "nocheckcertificate": True,
                            "socket_timeout": float(timeout_seconds),
                            "geo_bypass": True,
                            "ignoreerrors": False,
                            "ignore_config": True,  # 忽略全局配置文件，避免意外读取 Cookie
                            "impersonate": "chrome",
                            # "format": "bestaudio/best", # 移除强制格式，允许自动选择最佳可用格式（仅获取信息）
                            "http_headers": {"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
                            "extractor_args": {"youtube": {"player_client": client_set}},
                            "logger": logger,
                        }
                        if proxy_url:
                            opts["proxy"] = proxy_url
                        if cookiefile:
                            opts["cookiefile"] = cookiefile
                        elif cfb:
                            opts["cookiesfrombrowser"] = (cfb,)

                        try:
                            info = extract_info_with_format_rotation(opts)
                        except DownloadError as e:
                            last_msg = strip_ansi(str(e))
                            has_cookie_in_log = any(CookieManager.is_cookie_error(line) for line in logger.lines)
                            
                            # ⚡ 快速中断：致命网络错误（代理/DNS/连接拒绝）— 继续重试毫无意义
                            if is_fatal_network_error(last_msg):
                                raise RuntimeError(f"网络连接失败（代理/DNS 错误），已中断所有重试: {last_msg}") from e
                            
                            if CookieManager.is_cookie_error(last_msg) or has_cookie_in_log:
                                custom_err = RuntimeError(CookieManager.get_fatal_msg(last_msg, cfb))
                                if not cookiefile and not cfb:
                                    no_cookie_error = custom_err
                                    last_err = custom_err
                                else:
                                    last_cookie_error = custom_err
                                    if cfb:
                                        disabled_browsers.add(cfb)
                                    last_err = no_cookie_error if no_cookie_error else custom_err
                                continue
                                
                            if has_login_required([], last_msg) or "Sign in to confirm" in last_msg:
                                force_browser_cookie = True
                                last_err = RuntimeError("需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启、提供 cookies 文件或改用 Firefox。")
                                continue
                            
                            # 错误处理优化
                            if not cookiefile and not cfb:
                                no_cookie_error = e
                                last_err = e
                            else:
                                last_err = no_cookie_error if no_cookie_error else e

                            if "HTTP Error 429" in last_msg or "429" in last_msg:
                                time.sleep(2.5 * (attempt + 1))
                                continue
                            if cfb and CookieManager.is_cookie_error(last_msg):
                                if cfb:
                                    disabled_browsers.add(cfb)
                                continue
                            continue
                        except Exception as e:
                            if not cookiefile and not cfb:
                                no_cookie_error = e
                                last_err = e
                            else:
                                if no_cookie_error:
                                    last_err = no_cookie_error
                                elif CookieManager.is_cookie_error(e):
                                    if no_cookie_error:
                                        last_err = no_cookie_error
                                    else:
                                        last_err = e
                                else:
                                    last_err = e
                                    
                            if cfb and CookieManager.is_cookie_error(e):
                                if cfb:
                                    disabled_browsers.add(cfb)
                                continue
                            continue
                    
                        if info is not None:
                            if has_login_required(logger.lines):
                                force_browser_cookie = True
                                disabled_web = disabled_web or ("web" in client_set)
                                last_err = RuntimeError("需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。")
                                continue
                            if has_po_token_required(logger.lines) and any(c in {"android", "ios", "mweb"} for c in client_set):
                                last_err = RuntimeError("该客户端需要 PO Token，已降级到其他客户端。")
                                disabled_web = disabled_web or ("web" in client_set)
                                continue
                            if has_js_challenge_failure(logger.lines):
                                disabled_web = True
                                last_err = RuntimeError("JS challenge 失败，可能导致格式缺失。建议升级 yt-dlp 或更换网络。")
                                continue
                            break

                    if not isinstance(info, dict):
                        continue

                    video_id = str(info.get("id") or "")
                    subtitles = info.get("subtitles") or {}
                    auto = info.get("automatic_captions") or {}
                    merged: dict = {}
                    if isinstance(subtitles, dict):
                        merged.update(subtitles)
                    if isinstance(auto, dict):
                        for k, v in auto.items():
                            if k not in merged:
                                merged[k] = v

                    preferred = [l for l in langs if l and l != "all"]
                    try_langs = preferred or [str(k) for k in merged.keys()]
                    for lang in try_langs:
                        tracks = merged.get(lang)
                        if not isinstance(tracks, list) or not tracks:
                            continue
                        track = None
                        for t in tracks:
                            if isinstance(t, dict) and (t.get("ext") == "vtt" or str(t.get("ext") or "") == "vtt"):
                                track = t
                                break
                        if track is None:
                            for t in tracks:
                                if isinstance(t, dict):
                                    track = t
                                    break
                        if not isinstance(track, dict):
                            continue
                        url = str(track.get("url") or "")
                        if not url:
                            continue
                        url = maybe_force_vtt(url)

                        try:
                            r = sess.get(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
                            if r.status_code == 429:
                                retry_after = r.headers.get("Retry-After", "")
                                try:
                                    wait_s = int(retry_after)
                                except Exception:
                                    wait_s = 20
                                last_err = RuntimeError(f"timedtext 触发 429（Retry-After={retry_after or 'n/a'}）")
                                time.sleep(max(8, min(90, wait_s)))
                                continue
                            r.raise_for_status()
                        except requests.exceptions.HTTPError as e:
                            last_err = e
                            continue
                        except requests.exceptions.RequestException:
                            last_err = None
                            continue

                        raw = r.text or ""
                        text = vtt_to_text(raw) if raw else ""
                        if text.strip():
                            label = f"{video_id or ''}{' ' if video_id else ''}{lang}".strip()
                            return label, text

            return None

        def download_with_lang(sub_langs: list[str]) -> tuple[str, list[Path]]:
            nonlocal force_browser_cookie
            nonlocal last_err, last_video_id
            attempt_retries = max(1, int(retries))
            
            # 记录无 Cookie 时的错误
            no_cookie_error: Exception | None = None
            
            client_strategies = [["android"], ["ios"]] + ([["web_safari"], ["web"]] if allow_web_client else []) + [["tv"]]

            for attempt in range(attempt_retries + 1): # 多尝试一次以覆盖更多策略
                # 轮换客户端策略
                client_set = client_strategies[attempt % len(client_strategies)]
                if disabled_web and "web" in client_set:
                    continue
                
                # ua = random.choice(user_agents) # 不再手动指定 UA，让 yt-dlp 根据 client 自动匹配
                
                for cookiefile, cfb in CookieManager.get_sources(cookies_file, cookies_from_browser, force_browser_cookie):
                    if cfb and cfb in disabled_browsers:
                        continue
                    logger = YdlLogger()
                    opts: dict = {
                        "skip_download": True,
                        "writesubtitles": True,
                        "writeautomaticsub": True,
                        "subtitleslangs": sub_langs,
                        "subtitlesformat": "vtt",
                        "outtmpl": outtmpl,
                        "quiet": True,
                        "no_warnings": True,
                        "verbose": True,
                        "nocheckcertificate": True,
                        "sleep_interval": 2,
                        "max_sleep_interval": 6,
                        "retries": 1,
                        "fragment_retries": 1,
                        "extractor_retries": 1,
                        "socket_timeout": float(timeout_seconds),
                        "geo_bypass": True,
                        "ignoreerrors": False,
                        "ignore_config": True,
                        "impersonate": "chrome",
                        "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
                        "extractor_args": {"youtube": {"player_client": client_set}},
                        "logger": logger,
                    }
                    if proxy_url:
                        opts["proxy"] = proxy_url
                    if cookiefile:
                        opts["cookiefile"] = cookiefile
                    elif cfb:
                        opts["cookiesfrombrowser"] = (cfb,)

                    try:
                        info = extract_info_with_format_rotation(opts)
                        if not isinstance(info, dict):
                            continue
                        if has_login_required(logger.lines):
                            force_browser_cookie = True
                            disabled_web = disabled_web or ("web" in client_set)
                            last_err = RuntimeError("需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。")
                            continue
                        if has_po_token_required(logger.lines) and any(c in {"android", "ios", "mweb"} for c in client_set):
                            last_err = RuntimeError("该客户端需要 PO Token，已降级到其他客户端。")
                            disabled_web = disabled_web or ("web" in client_set)
                            continue
                        if has_js_challenge_failure(logger.lines):
                            disabled_web = True
                            last_err = RuntimeError("JS challenge 失败，可能导致格式缺失。建议升级 yt-dlp 或更换网络。")
                            continue
                        last_video_id = (info or {}).get("id") or last_video_id
                        last_err = None
                        subtitles = info.get("subtitles") or {}
                        auto = info.get("automatic_captions") or {}
                        merged: dict = {}
                        if isinstance(subtitles, dict):
                            merged.update(subtitles)
                        if isinstance(auto, dict):
                            for k, v in auto.items():
                                if k not in merged:
                                    merged[k] = v
                        preferred = [l for l in sub_langs if l and l != "all"]
                        try_langs = preferred or [str(k) for k in merged.keys()]
                        sess = build_download_session()
                        ua = random.choice(user_agents)
                        for lang in try_langs:
                            tracks = merged.get(lang)
                            if not isinstance(tracks, list) or not tracks:
                                continue
                            track = None
                            for t in tracks:
                                if isinstance(t, dict) and (t.get("ext") == "vtt" or str(t.get("ext") or "") == "vtt"):
                                    track = t
                                    break
                            if track is None:
                                for t in tracks:
                                    if isinstance(t, dict):
                                        track = t
                                        break
                            if not isinstance(track, dict):
                                continue
                            url = str(track.get("url") or "")
                            if not url:
                                continue
                            url = maybe_force_vtt(url)
                            try:
                                r = sess.get(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
                                if r.status_code == 429:
                                    retry_after = r.headers.get("Retry-After", "")
                                    try:
                                        wait_s = int(retry_after)
                                    except Exception:
                                        wait_s = 20
                                    last_err = RuntimeError(f"timedtext 触发 429（Retry-After={retry_after or 'n/a'}）")
                                    time.sleep(max(8, min(90, wait_s)))
                                    continue
                                r.raise_for_status()
                            except requests.exceptions.HTTPError as e:
                                last_err = e
                                continue
                            except requests.exceptions.RequestException:
                                last_err = None
                                continue
                            raw = r.text or ""
                            if raw.strip():
                                file_name = f"{last_video_id or 'video'}.{lang}.vtt"
                                vtt_path = Path(tmp) / file_name
                                vtt_path.write_text(raw, encoding="utf-8", errors="ignore")
                                return last_video_id, [vtt_path]
                        last_err = RuntimeError("yt-dlp 未下载到字幕文件（可能无字幕或被限制）。")
                        return last_video_id, []
                    except DownloadError as e:
                        msg = strip_ansi(str(e))
                        has_cookie_in_log = any(CookieManager.is_cookie_error(line) for line in logger.lines)
                        if CookieManager.is_cookie_error(msg) or has_cookie_in_log:
                            last_cookie_error = RuntimeError(CookieManager.get_fatal_msg(msg, cfb))
                            if cfb:
                                disabled_browsers.add(cfb)
                            continue
                        else:
                            last_err = RuntimeError(msg + "\n\n" + "\n".join(logger.lines[-80:]))
                            if not cookiefile and not cfb:
                                no_cookie_error = last_err
                            elif no_cookie_error:
                                last_err = no_cookie_error
                        if "HTTP Error 429" in msg or "429" in msg:
                            time.sleep(2.0 * (attempt + 1))
                            continue
                        if cfb and CookieManager.is_cookie_error(msg):
                            continue
                        continue
                    except Exception as e:
                        last_err = RuntimeError(repr(e) + "\n\n" + "\n".join(logger.lines[-80:]))
                        if not cookiefile and not cfb:
                            no_cookie_error = last_err
                        else:
                            if no_cookie_error:
                                last_err = no_cookie_error
                        if cfb and CookieManager.is_cookie_error(e):
                            continue
                        continue
            return last_video_id, []

        def try_timedtext_direct(video_id: str, langs_try: list[str]) -> tuple[str, str] | None:
            if not video_id:
                return None
            sess = build_download_session()
            ua = random.choice(user_agents)
            for lang in langs_try:
                for kind in ("", "asr"):
                    params = {"v": video_id, "lang": lang, "fmt": "vtt"}
                    if kind:
                        params["kind"] = kind
                    try:
                        r = sess.get(
                            "https://www.youtube.com/api/timedtext",
                            params=params,
                            headers={"User-Agent": ua, "Accept-Encoding": "identity"},
                        )
                        if r.status_code == 429:
                            retry_after = r.headers.get("Retry-After", "")
                            try:
                                wait_s = int(retry_after)
                            except Exception:
                                wait_s = 20
                            last_err = RuntimeError(f"timedtext 触发 429（Retry-After={retry_after or 'n/a'}）")
                            time.sleep(max(8, min(90, wait_s)))
                            continue
                        r.raise_for_status()
                    except requests.exceptions.RequestException as e:
                        last_err = e
                        continue
                    raw = r.text or ""
                    if is_html_like_text(raw):
                        last_err = RuntimeError("timedtext 返回 HTML 源码")
                        continue
                    text = vtt_to_text(raw) if raw else ""
                    if text.strip():
                        label = f"{video_id} {lang}{' asr' if kind else ''}".strip()
                        return label, text
            return None

        def choose_vtt(vtts: list[Path], lang: str | None) -> Path:
            if lang:
                for p in vtts:
                    if f".{lang}." in p.name or p.name.endswith(f".{lang}.vtt"):
                        return p
            return vtts[0]

        direct = try_extract_and_download_by_url()
        if direct is not None:
            return direct

        preferred = [l for l in langs if l and l != "all"]
        if preferred:
            for lang in preferred:
                last_video_id, vtts = download_with_lang([lang])
                if vtts:
                    chosen = choose_vtt(vtts, lang)
                    raw = chosen.read_text(encoding="utf-8", errors="ignore")
                    text = vtt_to_text(raw)
                    label = f"{last_video_id or ''}{' ' if last_video_id else ''}{chosen.name}".strip()
                    return label, text
        last_video_id, vtts = download_with_lang(["all"])
        if vtts:
            chosen = choose_vtt(vtts, None)
            raw = chosen.read_text(encoding="utf-8", errors="ignore")
            text = vtt_to_text(raw)
            label = f"{last_video_id or ''}{' ' if last_video_id else ''}{chosen.name}".strip()
            return label, text

        preferred = [l for l in langs if l and l != "all"]
        try_video_id = last_video_id
        if not try_video_id:
            try:
                try_video_id = extract_video_id(video_url)
            except Exception:
                try_video_id = ""
        timedtext = try_timedtext_direct(try_video_id, preferred or ["en", "zh-Hans", "zh", "zh-Hant"])
        if timedtext is not None:
            return timedtext

        if last_err is not None:
            raise last_err
        if last_cookie_error:
            raise last_cookie_error
        raise RuntimeError("yt-dlp 兜底抓取失败（未知原因）。")


def transcribe_audio_with_whisper(audio_path: str, model_name: str, language: str, proxy_url: str = None, status_callback=None, fast_mode: bool = False, force_cpu: bool = False) -> str:
    # 优先尝试使用 faster-whisper (速度快 4-10 倍)
    # 记录 faster-whisper 的错误信息，以便 fallback 时展示
    fw_error = None
    
    if status_callback: status_callback("Initializing Whisper engine...")

    try:
        from faster_whisper import WhisperModel
        
        # 设置临时环境变量以支持代理下载模型
        original_http = os.environ.get("HTTP_PROXY")
        original_https = os.environ.get("HTTPS_PROXY")
        
        if proxy_url:
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            print(f"Setting proxy for faster-whisper model download: {proxy_url}")
        
        def _safe_status(message: str) -> None:
            try:
                if status_callback:
                    status_callback(message)
            except Exception:
                pass

        def _get_wav_duration_seconds(path: str) -> float | None:
            try:
                with wave.open(path, "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate <= 0:
                        return None
                    return float(frames) / float(rate)
            except Exception:
                return None

        def _transcribe_in_worker(q: "queue.Queue[object]", transcribe_kwargs: dict) -> None:
            try:
                q.put(("begin", time.time()))
                segments_local, info_local = model.transcribe(audio_path, **transcribe_kwargs)

                text_segments_local: list[str] = []
                last_emit = time.time()
                seg_count = 0
                last_end_s: float | None = None
                for seg in segments_local:
                    seg_count += 1
                    text_segments_local.append(seg.text)
                    try:
                        last_end_s = float(getattr(seg, "end", None))
                    except Exception:
                        last_end_s = None
                    now = time.time()
                    if now - last_emit >= 10:
                        q.put(("progress", {"segments": seg_count, "end_s": last_end_s, "t": now}))
                        last_emit = now
                q.put(("done", {"text": "".join(text_segments_local).strip(), "info": info_local}))
            except Exception as e:
                q.put(("error", e))

        try:
            # 映射模型名称 (faster-whisper 使用同样的名称)
            model_size = (model_name or "").strip() or "base"
            
            # 初始化模型 (使用 int8 量化，CPU 上极快)
            # 缓存模型以避免重复加载
            cache_key = f"faster_whisper_{model_size}"
            cache = getattr(transcribe_audio_with_whisper, "_model_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(transcribe_audio_with_whisper, "_model_cache", cache)
                
            model = cache.get(cache_key)
            cache_info = cache.get(f"{cache_key}_info", {}) if isinstance(cache, dict) else {}
            cached_device = str(cache_info.get("device") or "").lower()
            cached_compute = str(cache_info.get("compute_type") or "").lower()
            gpu_failed_flag = bool(cache.get(f"{cache_key}_gpu_failed", False))
            gpu_retry_once = bool(cache.get(f"{cache_key}_gpu_retry_once", False))
            cuda_ready = False
            cuda_reason = ""
            ct2_version = ""
            ct2_cuda_count = None
            try:
                import ctranslate2
                ct2_version = str(getattr(ctranslate2, "__version__", "")) or "unknown"
                if hasattr(ctranslate2, "get_cuda_device_count"):
                    ct2_cuda_count = ctranslate2.get_cuda_device_count()
                    cuda_ready = ct2_cuda_count > 0
                    if not cuda_ready:
                        cuda_reason = "ctranslate2 reports no CUDA devices"
                        _safe_status("CUDA 不可用：ctranslate2 未检测到设备")
            except Exception as e:
                cuda_reason = f"ctranslate2 check failed: {e}"
            if model is not None:
                if status_callback:
                    status_callback(f"Using cached Whisper model ({cached_device or 'cpu'} {cached_compute or 'int8'})")
                if not force_cpu and cuda_ready and cached_device == "cpu":
                    if not gpu_failed_flag:
                        cache.pop(cache_key, None)
                        cache.pop(f"{cache_key}_info", None)
                        model = None
                    elif not gpu_retry_once:
                        cache[f"{cache_key}_gpu_retry_once"] = True
                        if status_callback:
                            status_callback("CUDA 可用，尝试重新加载 GPU 模型")
                        cache.pop(cache_key, None)
                        cache.pop(f"{cache_key}_info", None)
                        model = None

            if model is None:
                # 自动检测最佳设备
                # 1. 尝试 GPU (CUDA)
                # 2. 回退到 CPU
                
                cpu_threads = os.cpu_count() or 4
                
                # 尝试加载 GPU
                # 注意：ctranslate2 需要 CUDA 11.x 或 12.x 运行时库
                device = "cpu"
                compute_type = "int8"
                
                # 尝试自动配置 NVIDIA 库路径 (从 pip 包)
                try:
                    import nvidia.cublas
                    import nvidia.cudnn
                    
                    # 尝试不同的子模块结构，适配不同版本的 nvidia 包
                    cublas_path = None
                    cudnn_path = None
                    
                    # Case 1: nvidia.cublas.lib
                    try:
                        import nvidia.cublas.lib
                        cublas_path = os.path.dirname(nvidia.cublas.lib.__file__)
                    except ImportError:
                        pass
                        
                    # Case 2: nvidia.cublas.bin (some versions)
                    if not cublas_path:
                        try:
                            import nvidia.cublas.bin
                            cublas_path = os.path.dirname(nvidia.cublas.bin.__file__)
                        except ImportError:
                            pass
                            
                    # Case 3: 根目录 (如果 __init__.py 就在 lib 旁)
                    if not cublas_path and hasattr(nvidia.cublas, '__file__') and nvidia.cublas.__file__:
                        cublas_path = os.path.join(os.path.dirname(nvidia.cublas.__file__), "lib")
                        if not os.path.exists(cublas_path):
                            cublas_path = os.path.join(os.path.dirname(nvidia.cublas.__file__), "bin")

                    # 同理 cuDNN
                    try:
                        import nvidia.cudnn.lib
                        cudnn_path = os.path.dirname(nvidia.cudnn.lib.__file__)
                    except ImportError:
                        pass
                        
                    if not cudnn_path and hasattr(nvidia.cudnn, '__file__') and nvidia.cudnn.__file__:
                         cudnn_path = os.path.join(os.path.dirname(nvidia.cudnn.__file__), "lib")
                         if not os.path.exists(cudnn_path):
                             cudnn_path = os.path.join(os.path.dirname(nvidia.cudnn.__file__), "bin")

                    if cublas_path and os.path.exists(cublas_path) and cublas_path not in os.environ["PATH"]:
                        os.environ["PATH"] = cublas_path + os.pathsep + os.environ["PATH"]
                        if hasattr(os, "add_dll_directory"):
                            try:
                                os.add_dll_directory(cublas_path)
                            except Exception:
                                pass
                        print(f"Added NVIDIA cuBLAS to PATH: {cublas_path}")
                    
                    if cudnn_path and os.path.exists(cudnn_path) and cudnn_path not in os.environ["PATH"]:
                        os.environ["PATH"] = cudnn_path + os.pathsep + os.environ["PATH"]
                        if hasattr(os, "add_dll_directory"):
                            try:
                                os.add_dll_directory(cudnn_path)
                            except Exception:
                                pass
                        print(f"Added NVIDIA cuDNN to PATH: {cudnn_path}")
                        
                except Exception as e_nvidia:
                    print(f"Failed to auto-configure NVIDIA libraries from pip packages: {e_nvidia}")

                diag_lines = []
                try:
                    diag_lines.append(f"Python {platform.python_version()} {platform.architecture()[0]}")
                    diag_lines.append(f"OS {platform.system()} {platform.release()}")
                    if ct2_version:
                        diag_lines.append(f"ctranslate2 {ct2_version}")
                    if ct2_cuda_count is not None:
                        diag_lines.append(f"ctranslate2 CUDA devices {ct2_cuda_count}")
                    if status_callback and diag_lines:
                        status_callback(" | ".join(diag_lines))
                except Exception:
                    pass

                try:
                    dll_dirs = []
                    env_paths = []
                    env_cuda_vars = []
                    for k, v in os.environ.items():
                        if k.startswith("CUDA_PATH") and v:
                            env_paths.append(v)
                            env_cuda_vars.append(f"{k}={v}")
                    for base in env_paths:
                        cand = os.path.join(base, "bin")
                        if os.path.isdir(cand):
                            dll_dirs.append(cand)
                    cuda_root = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
                    if os.path.isdir(cuda_root):
                        for name in os.listdir(cuda_root):
                            cand = os.path.join(cuda_root, name, "bin")
                            if os.path.isdir(cand):
                                dll_dirs.append(cand)
                    site_paths = [p for p in sys.path if p and "site-packages" in p.lower()]
                    for sp in site_paths:
                        pattern = os.path.join(sp, "nvidia", "cublas", "**", "cublas64_*.dll")
                        for dll in glob.glob(pattern, recursive=True):
                            dll_dirs.append(os.path.dirname(dll))
                    seen = set()
                    added_dirs = []
                    for d in dll_dirs:
                        if d in seen:
                            continue
                        seen.add(d)
                        if d not in os.environ["PATH"]:
                            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
                            added_dirs.append(d)
                        if hasattr(os, "add_dll_directory"):
                            try:
                                os.add_dll_directory(d)
                            except Exception:
                                pass
                    if added_dirs:
                        print(f"Added CUDA DLL dirs: {len(added_dirs)}")
                        if status_callback:
                            status_callback(f"CUDA DLL dirs added: {len(added_dirs)}")
                    if status_callback:
                        preview_dirs = dll_dirs[:3]
                        status_callback(f"CUDA 搜索目录: {len(dll_dirs)} | 预览: {', '.join(preview_dirs) if preview_dirs else 'none'}")
                        if env_cuda_vars:
                            status_callback(f"CUDA 环境变量: {', '.join(env_cuda_vars[:3])}{'...' if len(env_cuda_vars) > 3 else ''}")
                except Exception as e_cuda_dirs:
                    print(f"Failed to auto-configure CUDA DLL dirs: {e_cuda_dirs}")

                # 显式打印正在加载模型，这在日志中可见
                print(f"Initializing faster-whisper model '{model_size}'...")
                
                import ctypes
                dll_candidates = [
                    "cublas64_12.dll",
                    "cublas64_11.dll",
                    "cublas64_10.dll",
                    "cublas64_10_2.dll",
                    "cudart64_12.dll",
                    "cudart64_11.dll",
                    "cudart64_10.dll",
                    "cudart64_10_2.dll",
                    "cudnn64_9.dll",
                    "cudnn64_8.dll",
                ]
                found_dlls = []
                failed_dlls = []
                found_paths = {}
                search_dirs = []
                try:
                    search_dirs.extend([p for p in os.environ.get("PATH", "").split(os.pathsep) if p])
                except Exception:
                    pass
                extra_dirs = locals().get("dll_dirs", [])
                if isinstance(extra_dirs, list):
                    search_dirs.extend(extra_dirs)
                seen_dirs = set()
                search_dirs = [d for d in search_dirs if d and not (d in seen_dirs or seen_dirs.add(d))]
                for name in dll_candidates:
                    loaded = False
                    try:
                        ctypes.CDLL(name)
                        loaded = True
                        found_paths[name] = name
                    except Exception:
                        pass
                    if not loaded:
                        for d in search_dirs:
                            dll_path = os.path.join(d, name)
                            if os.path.isfile(dll_path):
                                try:
                                    ctypes.CDLL(dll_path)
                                    loaded = True
                                    found_paths[name] = dll_path
                                    break
                                except Exception:
                                    pass
                    if loaded:
                        found_dlls.append(name)
                    else:
                        failed_dlls.append(name)

                has_cuda_libs = len(found_dlls) > 0
                if status_callback:
                    status_callback(f"CUDA DLL 探测: 命中 {len(found_dlls)} / 候选 {len(dll_candidates)}")
                    if found_paths:
                        preview_paths = list(found_paths.values())[:3]
                        status_callback(f"CUDA DLL 路径预览: {', '.join(preview_paths)}")
                    has_cublas = any(n.startswith("cublas") for n in found_dlls)
                    has_cudart = any(n.startswith("cudart") for n in found_dlls)
                    has_cudnn = any(n.startswith("cudnn") for n in found_dlls)
                    status_callback(f"CUDA DLL 族: cublas={has_cublas} cudart={has_cudart} cudnn={has_cudnn}")
                    if search_dirs:
                        for i in range(0, len(search_dirs), 8):
                            status_callback("CUDA 搜索目录清单: " + "; ".join(search_dirs[i:i+8]))
                    if found_paths:
                        items = [f"{k} -> {found_paths[k]}" for k in sorted(found_paths.keys())]
                        for i in range(0, len(items), 10):
                            status_callback("CUDA DLL 命中清单: " + "; ".join(items[i:i+10]))
                    if failed_dlls:
                        for i in range(0, len(failed_dlls), 10):
                            status_callback("CUDA DLL 未命中清单: " + ", ".join(failed_dlls[i:i+10]))
                if not has_cuda_libs:
                    msg = "⚠️ CUDA DLL 未找到，跳过 GPU，强制 CPU。"
                    print(msg)
                    if status_callback:
                        status_callback(msg)
                if not cuda_ready:
                    cuda_ready = has_cuda_libs
                    if not cuda_ready and not cuda_reason:
                        cuda_reason = "CUDA DLL 未找到"
                if status_callback and found_dlls:
                    status_callback(f"CUDA DLL 就绪: {', '.join(found_dlls[:3])}{'...' if len(found_dlls) > 3 else ''}")

                try:
                    if force_cpu:
                        raise RuntimeError("Forced CPU mode")
                    if not cuda_ready:
                        raise RuntimeError(f"CUDA not ready (Skipping): {cuda_reason}")

                    # 静默尝试 GPU (float16)
                    # 增加 download_root 参数，确保模型下载到项目目录下，方便管理且避免权限问题
                    # 使用 os.getcwd() 可能会变，建议用固定相对路径 "models"
                    model_dir = str(get_models_dir())
                    os.makedirs(model_dir, exist_ok=True)
                    
                    print(f"Attempting to load on GPU (cuda)... Download root: {model_dir}")
                    if status_callback: status_callback(f"Attempting to load Whisper on GPU (CUDA)...")
                    
                    # 1. 尝试 GPU float16 (最佳性能，但显存要求高)
                    try:
                        model = WhisperModel(model_size, device="cuda", compute_type="float16", download_root=model_dir)
                        device = "cuda"
                        compute_type = "float16"
                        print(f"✅ faster-whisper loaded on GPU (cuda) with float16. Threads: {cpu_threads}")
                        if status_callback: status_callback(f"✅ Whisper loaded on GPU (CUDA float16)")
                    except Exception as e_f16:
                        print(f"⚠️ GPU float16 load failed: {e_f16}")
                        
                        # 2. 尝试 GPU int8 (节省显存，适合 4GB 显存如 1050 Ti 跑 large 模型)
                        try:
                            print(f"Attempting to load on GPU (cuda) int8...")
                            if status_callback: status_callback(f"GPU float16 failed. Trying GPU int8...")
                            model = WhisperModel(model_size, device="cuda", compute_type="int8", download_root=model_dir)
                            device = "cuda"
                            compute_type = "int8"
                            print(f"✅ faster-whisper loaded on GPU (cuda) with int8. Threads: {cpu_threads}")
                            if status_callback: status_callback(f"✅ Whisper loaded on GPU (CUDA int8)")
                        except Exception as e_int8:
                            print(f"❌ GPU int8 load failed: {e_int8}")
                            import traceback
                            traceback.print_exc()
                            raise e_int8 # 抛出异常以触发外层的 CPU fallback
    
                except Exception as e:
                    print(f"GPU load failed completely ({e}), fallback to CPU int8")
                    if status_callback: status_callback(f"❌ GPU failed ({str(e)[:50]}...). Falling back to CPU.")
                    cache[f"{cache_key}_gpu_failed_reason"] = str(e)
                    # 3. 回退到 CPU int8
                    model_dir = str(get_models_dir())
                    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads, download_root=model_dir)
                    device = "cpu"
                    compute_type = "int8"
                    cache[f"{cache_key}_gpu_failed"] = True
                    print(f"✅ faster-whisper loaded on CPU with int8. Threads: {cpu_threads}")
                    if status_callback: status_callback(f"✅ Whisper loaded on CPU (int8)")
                
                # 记录 device 信息到 model 对象，方便外部读取（虽然 model 是 C++ 包装对象可能不支持随意 setattr）
                # 我们可以存到 cache 的 metadata 里
                cache[cache_key] = model
                cache[f"{cache_key}_info"] = {"device": device, "compute_type": compute_type}
                if device == "cuda":
                    cache[f"{cache_key}_gpu_failed"] = False
                    cache.pop(f"{cache_key}_gpu_failed_reason", None)
                
            # 开始转写
            lang = None if (not language or language == "auto") else language
            
            device_for_status = cache.get(f"{cache_key}_info", {}).get("device", "cpu")
            _safe_status(f"Transcribing audio with Whisper ({device_for_status})...")

            try:
                wav_seconds = _get_wav_duration_seconds(audio_path)
                if wav_seconds is not None:
                    _safe_status(f"Audio duration: {wav_seconds:.1f}s")

                used_device_now = str(cache.get(f"{cache_key}_info", {}).get("device", "cpu")).lower()
                used_compute_now = str(cache.get(f"{cache_key}_info", {}).get("compute_type", "int8")).lower()
                cpu_count = os.cpu_count() or 4
                running_on_render = bool(str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip())
                audio_minutes = (float(wav_seconds) / 60.0) if wav_seconds is not None else None
                batch_size = 8
                if used_device_now == "cuda":
                    # 针对 int8 和不同模型大小优化 batch_size
                    base_batch = 8
                    if model_size in {"tiny", "base"}:
                        base_batch = 24
                    elif model_size in {"small"}:
                        base_batch = 16
                    elif model_size in {"medium"}:
                        base_batch = 12
                    else: # large
                        base_batch = 6
                    
                    if used_compute_now == "int8":
                        # int8 显存占用更小，可以增加 batch_size 以提高吞吐量
                        base_batch = int(base_batch * 1.5)
                    
                    batch_size = base_batch
                    
                    if audio_minutes is not None and audio_minutes >= 90:
                        # 长音频适当保守一点，避免显存碎片化
                        batch_size = max(4, min(batch_size, 16))
                else:
                    base_cpu_batch = 20 if cpu_count >= 16 else (16 if cpu_count >= 8 else 8)
                    if model_size in {"tiny", "base", "small"}:
                        batch_size = base_cpu_batch
                    else:
                        batch_size = min(10, base_cpu_batch)
                    if audio_minutes is not None and audio_minutes >= 60:
                        batch_size = max(8, min(batch_size, 12))
                    if running_on_render:
                        batch_size = min(batch_size, 4)
                        _safe_status("Render 内存保护：已降低 CPU batch_size")

                auto_fast_mode = False
                if not fast_mode and wav_seconds is not None:
                    if used_device_now == "cpu" and wav_seconds >= 20 * 60:
                        auto_fast_mode = True
                        _safe_status("Auto fast mode: long audio on CPU")
                    elif used_device_now == "cuda" and wav_seconds >= 60 * 60:
                        auto_fast_mode = True
                        _safe_status("Auto fast mode: very long audio on CUDA")

                effective_fast_mode = bool(fast_mode or auto_fast_mode)

                vad_parameters = {"min_silence_duration_ms": 500}
                if wav_seconds is not None and wav_seconds >= 20 * 60:
                    vad_parameters = {"min_silence_duration_ms": 800, "speech_pad_ms": 150}
                fast_chunk_len = 60
                if effective_fast_mode:
                    fast_chunk_len = 30 if used_device_now == "cuda" else 60
                    vad_parameters = {"min_silence_duration_ms": 1000, "speech_pad_ms": 80}
                    _safe_status(f"Fast mode enabled: chunk_length={fast_chunk_len}, timestamps=off")

                transcribe_kwargs = {
                    "beam_size": 1,
                    "best_of": 1,
                    "temperature": 0.0,
                    "language": lang,
                    "condition_on_previous_text": False,
                    "vad_filter": True,
                    "vad_parameters": vad_parameters,
                    "without_timestamps": True,
                    "batch_size": int(batch_size),
                }
                if effective_fast_mode:
                    transcribe_kwargs["chunk_length"] = fast_chunk_len
                _safe_status(f"Whisper参数: device={used_device_now}, batch={batch_size}, chunk={transcribe_kwargs.get('chunk_length', 'auto')}, vad={vad_parameters.get('min_silence_duration_ms')}")
                try:
                    import inspect

                    accepted = set(inspect.signature(model.transcribe).parameters.keys())
                    dropped = sorted([k for k in transcribe_kwargs.keys() if k not in accepted])
                    transcribe_kwargs = {k: v for k, v in transcribe_kwargs.items() if k in accepted}
                    if dropped:
                        _safe_status(f"faster-whisper 参数兼容：已忽略 {', '.join(dropped)}")
                except Exception:
                    pass

                q: "queue.Queue[object]" = queue.Queue()
                worker = threading.Thread(target=_transcribe_in_worker, args=(q, transcribe_kwargs), daemon=True)
                started_at = time.time()
                worker.start()

                last_progress_at = started_at
                last_seg_count = 0
                last_end_s: float | None = None
                last_heartbeat_at = started_at
                max_total_seconds = max(30.0 * 60.0, float(wav_seconds) * 8.0) if wav_seconds is not None else 30.0 * 60.0
                stall_seconds = 10.0 * 60.0
                if str(device_for_status).lower() == "cuda":
                    max_total_seconds = max(60.0 * 60.0, float(wav_seconds) * 12.0) if wav_seconds is not None else 60.0 * 60.0
                    stall_seconds = max(2.0 * 60.0, float(wav_seconds) * 0.06) if wav_seconds is not None else 2.0 * 60.0
                    stall_cap = max_total_seconds * 0.4
                    if stall_seconds > stall_cap:
                        stall_seconds = stall_cap

                result_text: str | None = None
                info = None
                while True:
                    try:
                        msg = q.get(timeout=2.0)
                    except Exception:
                        msg = None

                    now = time.time()
                    if now - last_heartbeat_at >= 30.0:
                        hb = f"Whisper heartbeat: {int(now - started_at)}s elapsed"
                        if wav_seconds is not None:
                            hb += f", audio {wav_seconds:.1f}s"
                        if last_seg_count:
                            hb += f", segments {last_seg_count}"
                        if last_end_s is not None:
                            hb += f", last_end {last_end_s:.1f}s"
                        _safe_status(hb)
                        last_heartbeat_at = now

                    if msg is None:
                        if now - started_at > max_total_seconds:
                            raise TimeoutError(f"Whisper transcribe timeout after {int(now - started_at)}s")
                        if last_progress_at and now - last_progress_at > stall_seconds:
                            raise TimeoutError(f"Whisper appears stalled (no progress for {int(now - last_progress_at)}s)")
                        continue

                    kind = msg[0]
                    if kind == "progress":
                        payload = msg[1] if len(msg) > 1 else {}
                        last_seg_count = int(payload.get("segments") or last_seg_count)
                        try:
                            last_end_s = float(payload.get("end_s")) if payload.get("end_s") is not None else last_end_s
                        except Exception:
                            pass
                        last_progress_at = now
                        if wav_seconds is not None and last_end_s is not None:
                            pct = max(0.0, min(100.0, (last_end_s / wav_seconds) * 100.0))
                            _safe_status(f"Whisper progress: {pct:.1f}% ({last_end_s:.1f}/{wav_seconds:.1f}s), segments={last_seg_count}")
                        else:
                            _safe_status(f"Whisper progress: segments={last_seg_count}")
                    elif kind == "done":
                        payload = msg[1] if len(msg) > 1 else {}
                        result_text = str(payload.get("text") or "").strip()
                        info = payload.get("info")
                        break
                    elif kind == "error":
                        err = msg[1] if len(msg) > 1 else RuntimeError("Unknown transcribe error")
                        raise err

                text = (result_text or "").strip()
            except TimeoutError as te:
                if device_for_status == "cuda":
                    _safe_status(f"CUDA transcribe stalled, fallback to CPU. Reason: {te}")
                    cache[f"{cache_key}_gpu_failed_reason"] = f"CUDA stalled: {te}"
                    cache[f"{cache_key}_gpu_failed"] = True
                    cache[f"{cache_key}_gpu_retry_once"] = True
                    cpu_threads = os.cpu_count() or 4
                    model_dir = str(get_models_dir())
                    os.makedirs(model_dir, exist_ok=True)
                    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads, download_root=model_dir)
                    cache[cache_key] = model
                    cache[f"{cache_key}_info"] = {"device": "cpu", "compute_type": "int8"}
                    cache[f"{cache_key}_gpu_failed"] = True
                    device_for_status = "cpu"
                    _safe_status("Retry transcribe on CPU (int8)...")
                    used_device_now = "cpu"
                    batch_size = 16 if (os.cpu_count() or 4) >= 8 else 8
                    if model_size not in {"tiny", "base", "small"}:
                        batch_size = min(8, batch_size)
                    transcribe_kwargs = {
                        "beam_size": 1,
                        "best_of": 1,
                        "temperature": 0.0,
                        "language": lang,
                        "condition_on_previous_text": False,
                        "vad_filter": True,
                        "vad_parameters": vad_parameters,
                        "without_timestamps": True,
                        "batch_size": int(batch_size),
                    }
                    if effective_fast_mode:
                        transcribe_kwargs["chunk_length"] = 60
                    try:
                        import inspect

                        accepted = set(inspect.signature(model.transcribe).parameters.keys())
                        dropped = sorted([k for k in transcribe_kwargs.keys() if k not in accepted])
                        transcribe_kwargs = {k: v for k, v in transcribe_kwargs.items() if k in accepted}
                        if dropped:
                            _safe_status(f"faster-whisper 参数兼容：已忽略 {', '.join(dropped)}")
                    except Exception:
                        pass

                    q = queue.Queue()
                    worker = threading.Thread(target=_transcribe_in_worker, args=(q, transcribe_kwargs), daemon=True)
                    started_at = time.time()
                    worker.start()

                    last_progress_at = started_at
                    last_seg_count = 0
                    last_end_s = None
                    last_heartbeat_at = started_at
                    max_total_seconds = max(60.0 * 60.0, float(wav_seconds) * 12.0) if wav_seconds is not None else 60.0 * 60.0
                    stall_seconds = 5.0 * 60.0  # CPU fallback: 5 分钟无进度则认定卡死

                    result_text = None
                    info = None
                    while True:
                        try:
                            msg = q.get(timeout=2.0)
                        except Exception:
                            msg = None

                        now = time.time()
                        if now - last_heartbeat_at >= 30.0:
                            hb = f"Whisper heartbeat: {int(now - started_at)}s elapsed"
                            if wav_seconds is not None:
                                hb += f", audio {wav_seconds:.1f}s"
                            if last_seg_count:
                                hb += f", segments {last_seg_count}"
                            if last_end_s is not None:
                                hb += f", last_end {last_end_s:.1f}s"
                            _safe_status(hb)
                            last_heartbeat_at = now

                        if msg is None:
                            if now - started_at > max_total_seconds:
                                raise TimeoutError(f"Whisper transcribe timeout after {int(now - started_at)}s")
                            if last_progress_at and now - last_progress_at > stall_seconds:
                                raise TimeoutError(f"Whisper appears stalled (no progress for {int(now - last_progress_at)}s)")
                            continue

                        kind = msg[0]
                        if kind == "progress":
                            payload = msg[1] if len(msg) > 1 else {}
                            last_seg_count = int(payload.get("segments") or last_seg_count)
                            try:
                                last_end_s = float(payload.get("end_s")) if payload.get("end_s") is not None else last_end_s
                            except Exception:
                                pass
                            last_progress_at = now
                            if wav_seconds is not None and last_end_s is not None:
                                pct = max(0.0, min(100.0, (last_end_s / wav_seconds) * 100.0))
                                _safe_status(f"Whisper progress: {pct:.1f}% ({last_end_s:.1f}/{wav_seconds:.1f}s), segments={last_seg_count}")
                            else:
                                _safe_status(f"Whisper progress: segments={last_seg_count}")
                        elif kind == "done":
                            payload = msg[1] if len(msg) > 1 else {}
                            result_text = str(payload.get("text") or "").strip()
                            info = payload.get("info")
                            break
                        elif kind == "error":
                            err = msg[1] if len(msg) > 1 else RuntimeError("Unknown transcribe error")
                            raise err

                    text = (result_text or "").strip()
                else:
                    raise
            
            # 获取实际使用的 device info
            dev_info = cache.get(f"{cache_key}_info", {})
            used_device = dev_info.get("device", "cpu")
            used_compute = dev_info.get("compute_type", "int8")
            
            # 附加 device 信息到文本末尾 (隐式传递给 UI)
            # 格式：<!-- FW_DEVICE: device_name (compute_type) -->
            debug_extra = ""
            if used_device != "cuda":
                gpu_failed_reason = cache.get(f"{cache_key}_gpu_failed_reason")
                if gpu_failed_reason:
                    reason_clean = str(gpu_failed_reason).replace("\n", " ").strip()
                    if len(reason_clean) > 140:
                        reason_clean = reason_clean[:140] + "..."
                    debug_extra = f" | GPU_FAIL: {reason_clean}"
            debug_tag = f"\n\n<!-- FW_DEVICE: {used_device.upper()} ({used_compute}){debug_extra} -->"
            
            if not text:
                 raise RuntimeError(f"faster-whisper 转写结果为空。Device: {used_device}")
            return text + debug_tag

        finally:
            # 恢复环境变量
            if proxy_url:
                if original_http:
                    os.environ["HTTP_PROXY"] = original_http
                else:
                    os.environ.pop("HTTP_PROXY", None)
                    
                if original_https:
                    os.environ["HTTPS_PROXY"] = original_https
                else:
                    os.environ.pop("HTTPS_PROXY", None)

    except ImportError:
        # 如果没有安装 faster-whisper，打印警告并回退到 openai-whisper
        print("Warning: 'faster-whisper' not installed. Using slower 'openai-whisper'. Install faster-whisper for 4x speedup.")
        pass
    except Exception as e:
        # faster-whisper 失败，回退到 openai-whisper
        fw_error = str(e)
        print(f"faster-whisper failed: {e}. Falling back to openai-whisper.")
        import traceback
        traceback.print_exc()
        pass

    # --- 以下是原有的 openai-whisper 逻辑 (作为兜底) ---
    try:
        import whisper  # type: ignore
    except Exception as e:
        msg = "未安装 openai-whisper，无法启用音频转写兜底。"
        if fw_error:
            msg += f"\n(此前 faster-whisper 也失败了: {fw_error})"
        raise RuntimeError(msg) from e
        
    print("Fallback to openai-whisper (Legacy)...")
    
    # 尝试获取 device (虽然 openai-whisper 自动处理，但我们可以尝试检测)
    import torch
    used_device = "CUDA" if torch.cuda.is_available() else "CPU"
    used_compute = "float16" if used_device == "CUDA" else "float32" # 简单假设


    model_name = (model_name or "").strip() or "base"
    language = (language or "").strip().lower()
    lang = None if (not language or language == "auto") else language

    cache = getattr(transcribe_audio_with_whisper, "_model_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(transcribe_audio_with_whisper, "_model_cache", cache)
    model = cache.get(model_name)
    if model is None:
        model = whisper.load_model(model_name)
        cache[model_name] = model
    
    # 定义重试参数列表
    # 策略优化：优先使用 Greedy (beam_size=1)，极大提升速度 (3-5x)
    # 如果 Greedy 失败，再尝试更稳健的 Beam Search 或 强力兜底
    
    retry_configs = [
        # 1. 极速模式：Greedy Decoding
        {"fp16": False, "language": lang, "beam_size": 1}, 
        # 2. 强力兜底：禁用所有过滤，强制输出
        {"fp16": False, "language": lang, "logprob_threshold": None, "compression_ratio_threshold": None, "condition_on_previous_text": False, "no_speech_threshold": 0.95},
    ]

    last_exc = None
    for i, cfg in enumerate(retry_configs):
        try:
            # print(f"Whisper attempt {i+1} with config: {cfg}")
            result = model.transcribe(audio_path, **cfg)
            text = str((result or {}).get("text") or "").strip()
            if text:
                 # 附加 openai-whisper 的 device info
                extra_msg = f" | ⚠️ faster-whisper 启动失败: {fw_error}" if fw_error else ""
                debug_tag = f"\n\n<!-- FW_DEVICE: {used_device} ({used_compute}) [OpenAI-Whisper]{extra_msg} -->"
                return text + debug_tag
        except Exception as e:
            last_exc = e
            # 如果是 KeyError (Linear)，直接抛出，无法重试修复
            if isinstance(e, KeyError) and "Linear" in str(e):
                raise KeyError(f"Whisper 模型加载/推理时发生 KeyError: {e}。这通常是 pytorch/whisper 版本不兼容导致。") from e
            # 继续尝试下一个配置

    # 所有重试都失败
    if last_exc:
        msg = str(last_exc)
        # 获取文件大小信息，辅助 debug
        file_info = ""
        try:
            sz = os.path.getsize(audio_path)
            file_info = f" (音频文件大小: {sz} bytes)"
        except:
            pass
            
        # 附加 device 信息到错误消息 (隐式传递给 UI)
        # 既然 faster-whisper 的 device info 很有用，这里也尝试获取一下
        # 虽然这里是 openai-whisper，但我们可以简单返回 CPU
        # 或者我们统一异常格式
        
        if "cannot reshape tensor of 0 elements" in msg:
            raise RuntimeError(f"音频转写失败：未能检测到有效语音片段 (No speech detected)。请检查视频是否静音，或尝试更小的模型{file_info}。") from last_exc
        raise last_exc
    
    raise RuntimeError("音频转写结果为空 (所有重试方案均未产生文本)。")



def transcribe_video_audio_with_ytdlp(
    video_url: str,
    proxy_url: str,
    timeout_seconds: float,
    retries: int,
    cookies_file: str,
    cookies_from_browser: str,
    model_name: str,
    language: str,
    status_callback=None,
    fast_mode: bool = False,
    cookie_debug_summary: str = "",
) -> tuple[str, str]:
    class YdlLogger:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def _add(self, level: str, msg: str) -> None:
            s = strip_ansi(str(msg or "")).strip()
            if not s:
                return
            self.lines.append(f"[{level}] {s}")
            if len(self.lines) > 400:
                self.lines = self.lines[-250:]

        def debug(self, msg: str) -> None:
            self._add("debug", msg)

        def info(self, msg: str) -> None:
            self._add("info", msg)

        def warning(self, msg: str) -> None:
            self._add("warning", msg)

        def error(self, msg: str) -> None:
            self._add("error", msg)

    try:
        from yt_dlp import YoutubeDL  # type: ignore
        from yt_dlp.utils import DownloadError  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "未安装 yt-dlp，无法启用音频转写兜底。可执行：python -m pip install yt-dlp -i https://pypi.tuna.tsinghua.edu.cn/simple"
        ) from e

        # 移除 detect_js_runtime 的定义，改用 yt-dlp 原生解释器或 yt_dlp_ejs
        # 移除此处的本地 is_cookie_error 定义，改用顶层的 _is_cookie_error

    normalized_video_url = normalize_video_url(video_url)
    parsed_video_host = (urlparse(normalized_video_url).netloc or "").lower()
    is_youtube_url = ("youtube.com" in parsed_video_host) or ("youtu.be" in parsed_video_host)
    is_bilibili_url = ("bilibili.com" in parsed_video_host) or ("b23.tv" in parsed_video_host)

    cache_path = _audio_cache_path(normalized_video_url)
    if cache_path and cache_path.exists():
        try:
            if cache_path.stat().st_size > 16 * 1024:
                if status_callback:
                    status_callback("检测到音频缓存，跳过下载")
                force_cpu_flag = bool(getattr(transcribe_video_audio_with_ytdlp, "_force_cpu", False))
                text = transcribe_audio_with_whisper(str(cache_path), model_name=model_name, language=language, proxy_url=proxy_url, status_callback=status_callback, fast_mode=fast_mode, force_cpu=force_cpu_flag)
                label = f"{_audio_cache_key(normalized_video_url)} | whisper:{(model_name or '').strip() or 'base'}"
                return label, text
        except Exception:
            pass

    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        last_err: Exception | None = None
        last_cookie_error: RuntimeError | None = None
        last_video_id = ""
        last_attempt_note = ""
        last_debug_lines: list[str] = []
        
        # 记录无 Cookie 时的错误
        no_cookie_error: Exception | None = None
        force_browser_cookie = False

        js_runtime_available, js_runtime_name = detect_js_runtime()
        running_on_render = bool(str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip())
        web_clients_enabled = bool(js_runtime_available and not running_on_render)
        has_cookie_hint = bool((cookies_file or "").strip()) or bool((cookies_from_browser or "").strip())
        if is_youtube_url:
            client_strategies = [["tv"], ["web_safari"]]
            if not has_cookie_hint:
                client_strategies.extend([["ios"], ["android"]])
            if not running_on_render:
                client_strategies.append(["mweb"])
            if web_clients_enabled:
                client_strategies.extend([["web_creator"], []])
        else:
            client_strategies = [[]]
        client_plan = ", ".join("+".join(cs) if cs else "default" for cs in client_strategies)

        if fast_mode:
            format_candidates = ["worstaudio/worst", "bestaudio/best", None]
        else:
            format_candidates = ["bestaudio/best", "worstaudio/worst", None]
        
        disabled_browsers: set[str] = set()
        disabled_clients_reason: dict[str, str] = {}
        cookie_file_exists = bool((cookies_file or "").strip()) and os.path.exists((cookies_file or "").strip())
        cookie_runtime_hint = (
            f"input_cookie_file={'yes' if (cookies_file or '').strip() else 'no'}; "
            f"input_cookie_exists={'yes' if cookie_file_exists else 'no'}; "
            f"input_browser={cookies_from_browser or 'none'}; "
            f"js_runtime_available={'yes' if js_runtime_available else 'no'}; "
            f"js_runtime={js_runtime_name}; "
            f"running_on_render={'yes' if running_on_render else 'no'}; "
            f"web_clients_enabled={'yes' if web_clients_enabled else 'no'}; "
            f"client_plan={client_plan}"
        )
        selected_audio_summary = ""
        runtime_version_summary = build_runtime_version_diagnostics()
        
        start_time = time.time()
        requested_paths: list[Path] = []
        download_ready = False
        last_err_type = ""
        last_traceback_text = ""
        
        for client_set in client_strategies:
            for attempt in range(max(1, int(retries)) + 1):
                for cookiefile, cfb in CookieManager.get_sources(cookies_file, cookies_from_browser, force_browser_cookie):
                    if cfb and cfb in disabled_browsers:
                        continue
                    for fmt in format_candidates:
                        if download_ready:
                            break
                        client_label = ",".join(client_set) if client_set else "default"
                        attempt_note = f"client={client_label} fmt={(fmt or 'default')} cookie={'file' if cookiefile else ('browser' if cfb else 'none')}"

                        def progress_hook(d):
                            if status_callback:
                                if d["status"] == "downloading":
                                    p = strip_ansi(str(d.get("_percent_str") or "")).replace("%", "")
                                    e = strip_ansi(str(d.get("_eta_str") or ""))
                                    status_callback(f"Downloading audio: {p}% (ETA: {e})")
                                elif d["status"] == "finished":
                                    status_callback("Download complete, preparing transcription...")

                        logger = YdlLogger()
                        opts: dict = {
                            "progress_hooks": [progress_hook],
                            "outtmpl": outtmpl,
                            "noplaylist": True,
                            "quiet": True,
                            "no_warnings": True,
                            "verbose": True,
                            "nocheckcertificate": True,
                            "socket_timeout": float(timeout_seconds),
                            "retries": 1,
                            "ignoreerrors": False,
                            "ignore_config": True,
                            "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
                            "logger": logger,
                        }
                        if is_bilibili_url:
                            opts["http_headers"].update({
                                "Referer": "https://www.bilibili.com/",
                                "Origin": "https://www.bilibili.com",
                            })
                        if is_youtube_url and client_set:
                            opts["extractor_args"] = {"youtube": {"player_client": client_set}}
                        if ffmpeg_binary_path:
                            opts["ffmpeg_location"] = ffmpeg_binary_path
                        if proxy_url:
                            opts["proxy"] = proxy_url
                        if cookiefile:
                            opts["cookiefile"] = cookiefile
                        elif cfb:
                            opts["cookiesfrombrowser"] = (cfb,)

                        try:
                            with YoutubeDL(opts) as ydl:
                                def pick_audio_format_entry(info: dict, prefer_worst: bool, preferred_ext: str | None = None) -> dict | None:
                                    formats = info.get("formats") if isinstance(info, dict) else None
                                    if not formats:
                                        return None
                                    audio_formats = []
                                    for item in formats:
                                        if not isinstance(item, dict):
                                            continue
                                        acodec = item.get("acodec")
                                        if not acodec or acodec == "none":
                                            continue
                                        if preferred_ext:
                                            ext = str(item.get("ext") or "").lower()
                                            if ext != preferred_ext.lower():
                                                continue
                                        audio_formats.append(item)
                                    if not audio_formats:
                                        return None

                                    def score(item: dict) -> float:
                                        for key in ("abr", "tbr"):
                                            val = item.get(key)
                                            if isinstance(val, (int, float)):
                                                return float(val)
                                        return 0.0

                                    return min(audio_formats, key=score) if prefer_worst else max(audio_formats, key=score)

                                def pick_audio_format(info: dict, prefer_worst: bool, preferred_ext: str | None = None) -> str | None:
                                    picked = pick_audio_format_entry(info, prefer_worst, preferred_ext)
                                    fid = picked.get("format_id") if isinstance(picked, dict) else None
                                    return str(fid) if fid else None

                                def has_audio_format(info: dict) -> bool:
                                    return pick_audio_format(info, False, None) is not None or pick_audio_format(info, True, None) is not None

                                def summarize_audio_entry(info: dict, chosen_entry: dict | None) -> str:
                                    formats = info.get("formats") if isinstance(info, dict) else None
                                    audio_count = 0
                                    if isinstance(formats, list):
                                        for item in formats:
                                            if isinstance(item, dict) and item.get("acodec") not in (None, "", "none"):
                                                audio_count += 1
                                    if not isinstance(chosen_entry, dict):
                                        return f"audio_format_count={audio_count}; selected=none"
                                    return (
                                        f"audio_format_count={audio_count}; "
                                        f"selected_format_id={chosen_entry.get('format_id') or 'unknown'}; "
                                        f"selected_ext={chosen_entry.get('ext') or 'unknown'}; "
                                        f"selected_protocol={chosen_entry.get('protocol') or 'unknown'}"
                                    )

                                def direct_download_audio(format_info: dict | None, output_dir: str) -> Path | None:
                                    """在 yt-dlp 没有落地产物时，直接下载可访问的音频流。"""
                                    if not isinstance(format_info, dict):
                                        return None
                                    audio_url = str(format_info.get("url") or "").strip()
                                    if not audio_url:
                                        return None
                                    protocol = str(format_info.get("protocol") or "").lower()

                                    ext = str(format_info.get("ext") or "bin").lower() or "bin"
                                    format_id = str(format_info.get("format_id") or "direct")
                                    base_name = last_video_id or "audio"
                                    target_path = Path(output_dir) / f"{base_name}.{format_id}.{ext}"

                                    session = TimeoutSession(timeout_seconds=max(5.0, float(timeout_seconds)))
                                    session.trust_env = True
                                    if proxy_url:
                                        session.trust_env = False
                                        session.proxies = {"http": proxy_url, "https": proxy_url}

                                    headers = dict(opts.get("http_headers") or {})
                                    headers["Referer"] = normalized_video_url

                                    if "m3u8" in protocol or "dash" in protocol:
                                        if not ffmpeg_binary_path or not os.path.exists(ffmpeg_binary_path):
                                            logger.warning("Direct media download fallback skipped: ffmpeg binary is unavailable for streaming protocol")
                                            return None
                                        ffmpeg_output = Path(output_dir) / f"{base_name}.{format_id}.m4a"
                                        ffmpeg_cmd = [
                                            ffmpeg_binary_path,
                                            "-y",
                                            "-nostdin",
                                            "-loglevel",
                                            "error",
                                        ]
                                        user_agent = str(headers.get("User-Agent") or "").strip()
                                        referer = str(headers.get("Referer") or "").strip()
                                        if user_agent:
                                            ffmpeg_cmd.extend(["-user_agent", user_agent])
                                        if referer:
                                            ffmpeg_cmd.extend(["-headers", f"Referer: {referer}\r\n"])
                                        ffmpeg_cmd.extend([
                                            "-i",
                                            audio_url,
                                            "-vn",
                                            "-acodec",
                                            "copy",
                                            str(ffmpeg_output),
                                        ])
                                        try:
                                            completed = subprocess.run(
                                                ffmpeg_cmd,
                                                capture_output=True,
                                                text=True,
                                                timeout=max(30, int(float(timeout_seconds) * 2)),
                                                check=False,
                                            )
                                            if completed.returncode == 0 and ffmpeg_output.exists() and ffmpeg_output.stat().st_size > 16 * 1024:
                                                logger.info("Direct media download fallback succeeded via ffmpeg streaming capture")
                                                return ffmpeg_output
                                            stderr_tail = (completed.stderr or "").strip()[-500:]
                                            logger.warning(f"Direct media download fallback via ffmpeg failed: {stderr_tail}")
                                        except Exception as e:
                                            logger.warning(f"Direct media download fallback via ffmpeg failed: {e}")
                                        return None

                                    try:
                                        with session.get(audio_url, headers=headers, stream=True, timeout=max(5.0, float(timeout_seconds))) as resp:
                                            resp.raise_for_status()
                                            with open(target_path, "wb") as fp:
                                                for chunk in resp.iter_content(chunk_size=1024 * 512):
                                                    if chunk:
                                                        fp.write(chunk)
                                        if target_path.exists() and target_path.stat().st_size > 16 * 1024:
                                            return target_path
                                    except Exception as e:
                                        logger.warning(f"Direct media download fallback failed: {e}")
                                    return None

                                try:
                                    if client_set and any(c in disabled_clients_reason for c in client_set):
                                        reason = next((disabled_clients_reason.get(c) for c in client_set if c in disabled_clients_reason), "Client disabled")
                                        if last_err is None:
                                            last_err = RuntimeError(reason)
                                        continue

                                    info = ydl.extract_info(normalized_video_url, download=False, process=False)
                                except DownloadError as e:
                                    msg = strip_ansi(str(e))
                                    has_cookie_in_log = any(CookieManager.is_cookie_error(line) for line in logger.lines)
                                    if CookieManager.is_cookie_error(msg) or has_cookie_in_log:
                                        last_cookie_error = RuntimeError(CookieManager.get_fatal_msg(msg, cfb))
                                        if cfb:
                                            disabled_browsers.add(cfb)
                                        continue
                                    if "missing a URL" in msg or "SABR streaming" in msg:
                                        if "web_safari" in client_set:
                                            disabled_clients_reason["web_safari"] = "Web Safari 客户端不兼容 (SABR/Missing URL)。"
                                        last_err = RuntimeError("Web Safari 客户端不兼容。")
                                        last_attempt_note = attempt_note + " (web_safari issue)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if "po token" in msg.lower() or "challenge solving failed" in msg.lower() or "only images are available" in msg.lower():
                                        force_browser_cookie = True
                                        last_err = RuntimeError("YouTube 触发挑战校验（PO Token/JS Challenge）。已自动切换为浏览器 Cookie 方案重试。")
                                        last_attempt_note = attempt_note + " (challenge/po token)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if has_login_required([], msg) and not (is_bilibili_url and has_premium_only_warning([], msg)):
                                        force_browser_cookie = True
                                        for c in client_set:
                                            if c in {"tv", "tv_embedded"}:
                                                disabled_clients_reason[c] = "需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。"
                                        last_err = RuntimeError("需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。")
                                        last_attempt_note = attempt_note + " (login required)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if "requested format not available" in msg.lower():
                                        last_err = e
                                        last_attempt_note = attempt_note
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if "drm protected" in msg.lower():
                                        if "tv" in client_set:
                                            disabled_clients_reason["tv"] = "TV 客户端遭遇 DRM 保护限制。"
                                        last_err = RuntimeError("当前客户端遭遇 DRM 保护限制。")
                                        last_attempt_note = attempt_note + " (DRM protected)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    raise e

                                try:
                                    if has_login_required(logger.lines) and not (is_bilibili_url and has_premium_only_warning(logger.lines)):
                                        force_browser_cookie = True
                                        for c in client_set:
                                            if c in {"tv", "tv_embedded"}:
                                                disabled_clients_reason[c] = "需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。"
                                        last_err = RuntimeError("需要登录或验证（可能触发人机校验）。已尝试自动读取浏览器 Cookie；如仍失败请手动开启或提供 cookies 文件。")
                                        last_attempt_note = attempt_note + " (login required)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if has_po_token_required(logger.lines) and any(c in {"android", "ios", "mweb"} for c in client_set):
                                        force_browser_cookie = True
                                        for c in client_set:
                                            if c in {"android", "ios", "mweb"}:
                                                disabled_clients_reason[c] = "该客户端需要 PO Token，已降级到其他客户端。"
                                        last_err = RuntimeError("该客户端需要 PO Token，已降级到其他客户端。")
                                        last_attempt_note = attempt_note + " (po token required)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue
                                    if has_js_challenge_failure(logger.lines):
                                        web_like_client = (not client_set) or any(c in {"web", "web_creator", "web_safari"} for c in client_set)
                                        if web_like_client:
                                            force_browser_cookie = True
                                            if "web" in client_set or "web_creator" in client_set:
                                                disabled_clients_reason["web"] = "JS challenge 失败，可能导致格式缺失。建议升级 yt-dlp 或更换网络。"
                                            last_err = RuntimeError("JS challenge 失败，可能导致格式缺失。建议升级 yt-dlp 或更换网络。")
                                            last_attempt_note = attempt_note + " (js challenge failed)"
                                            last_debug_lines = logger.lines[-80:]
                                            continue
                                    if not has_audio_format(info):
                                        if "web" in client_set:
                                            disabled_clients_reason["web"] = "未检测到可用音频格式。建议升级 yt-dlp 或更换网络。"
                                        last_err = RuntimeError("未检测到可用音频格式。建议升级 yt-dlp 或更换网络。")
                                        last_attempt_note = attempt_note + " (no audio formats)"
                                        last_debug_lines = logger.lines[-80:]
                                        continue

                                    selected_audio_entry = pick_audio_format_entry(info, False, None)
                                    selected_audio_summary = summarize_audio_entry(info, selected_audio_entry)
                                    if fmt:
                                        prefer_worst = fmt in {"worstaudio/worst", "worstaudio", "worst"}
                                        chosen = pick_audio_format(info, prefer_worst, None)
                                        selected_audio_entry = pick_audio_format_entry(info, prefer_worst, None)
                                        selected_audio_summary = summarize_audio_entry(info, selected_audio_entry)
                                        if chosen:
                                            ydl.params["format"] = chosen
                                        else:
                                            last_err = RuntimeError("Requested format is not available")
                                            last_attempt_note = attempt_note
                                            last_debug_lines = logger.lines[-80:]
                                            continue

                                    requested_paths = []
                                    direct_file = direct_download_audio(selected_audio_entry, tmp)
                                    if direct_file:
                                        requested_paths.append(direct_file)
                                        if isinstance(info, dict):
                                            last_video_id = str(info.get("id") or last_video_id)
                                    else:
                                        info = ydl.extract_info(normalized_video_url, download=True)
                                        if isinstance(info, dict):
                                            last_video_id = str(info.get("id") or last_video_id)
                                            requested_downloads = info.get("requested_downloads") or []
                                            if isinstance(requested_downloads, list):
                                                for item in requested_downloads:
                                                    if isinstance(item, dict):
                                                        fp = item.get("filepath")
                                                        if fp:
                                                            requested_paths.append(Path(str(fp)))
                                            requested_formats = info.get("requested_formats") or []
                                            if isinstance(requested_formats, list):
                                                for item in requested_formats:
                                                    if isinstance(item, dict):
                                                        fp = item.get("filepath")
                                                        if fp:
                                                            requested_paths.append(Path(str(fp)))
                                            direct_fp = info.get("filepath")
                                            if direct_fp:
                                                requested_paths.append(Path(str(direct_fp)))

                                        if not requested_paths:
                                            if isinstance(selected_audio_entry, dict):
                                                selected_protocol = str(selected_audio_entry.get("protocol") or "").lower() or "unknown"
                                                selected_ext = str(selected_audio_entry.get("ext") or "").lower() or "unknown"
                                                last_err = RuntimeError(f"直链下载与 yt-dlp 下载均未产出文件（protocol={selected_protocol}, ext={selected_ext}）")
                                                last_err_type = type(last_err).__name__
                                                last_attempt_note = attempt_note + " (no output files)"
                                                last_debug_lines = logger.lines[-80:]
                                                continue
                                            else:
                                                last_err = RuntimeError("yt-dlp 未返回可用音频入口摘要，无法执行下载。")
                                                last_err_type = type(last_err).__name__
                                                last_attempt_note = attempt_note + " (no selected audio entry)"
                                                last_debug_lines = logger.lines[-80:]
                                                continue
                                    last_err = None
                                    last_err_type = ""
                                    last_traceback_text = ""
                                    download_ready = True
                                    break
                                except DownloadError as dl_err:
                                    last_err = dl_err
                                    last_err_type = type(dl_err).__name__
                                    last_traceback_text = traceback.format_exc()
                                    last_attempt_note = attempt_note
                                    last_debug_lines = logger.lines[-80:]
                                    if "HTTP Error 429" in strip_ansi(str(dl_err)):
                                        time.sleep(2.0 * (attempt + 1))
                                    continue
                                except Exception as dl_err:
                                    last_err = dl_err
                                    last_err_type = type(dl_err).__name__
                                    last_traceback_text = traceback.format_exc()
                                    last_attempt_note = attempt_note
                                    last_debug_lines = logger.lines[-80:]
                                    continue

                        except DownloadError as e:
                            msg = strip_ansi(str(e))
                            has_cookie_in_log = any(CookieManager.is_cookie_error(line) for line in logger.lines)
                            if CookieManager.is_cookie_error(msg) or has_cookie_in_log:
                                last_cookie_error = RuntimeError(CookieManager.get_fatal_msg(msg, cfb))
                                if cfb:
                                    disabled_browsers.add(cfb)
                                continue
                            if ("ejs" in msg.lower()) or ("challenge solving failed" in msg.lower()) or ("js runtimes: none" in msg.lower()) or ("only images are available" in msg.lower()):
                                disabled_clients_reason["web"] = "Web 客户端挑战失败，已禁用。"
                                last_attempt_note = attempt_note + " (EJS/JS runtime issue, web disabled)"
                                last_debug_lines = logger.lines[-80:]
                                continue
                            if not cookiefile and not cfb:
                                no_cookie_error = e
                                last_err = e
                            else:
                                last_err = no_cookie_error if no_cookie_error else e
                            last_err_type = type(last_err).__name__ if last_err else ""
                            last_traceback_text = traceback.format_exc()
                            last_attempt_note = attempt_note
                            last_debug_lines = logger.lines[-80:]
                            if "HTTP Error 429" in msg or "429" in msg:
                                time.sleep(2.0 * (attempt + 1))
                            continue
                        except Exception as e:
                            if not cookiefile and not cfb:
                                no_cookie_error = e
                                last_err = e
                            else:
                                if no_cookie_error:
                                    last_err = no_cookie_error
                                elif not CookieManager.is_cookie_error(str(e)):
                                    last_err = e
                            last_err_type = type(last_err).__name__ if last_err else ""
                            last_traceback_text = traceback.format_exc()
                            last_attempt_note = attempt_note
                            last_debug_lines = logger.lines[-80:]
                            continue

                    if download_ready:
                        break

                if last_err is None:
                    # 成功获取到信息（且下载成功），不需要再重试其他 client
                    pass

                media_suffixes = {".m4a", ".webm", ".mp3", ".wav", ".opus", ".aac", ".flac", ".ogg", ".mp4", ".mkv", ".mov", ".m4v", ".ts", ".m4s"}
                candidates = []
                temp_outputs = []
                for p in Path(tmp).rglob("*"):
                    if not p.is_file():
                        continue
                    temp_outputs.append(f"{p.name} ({p.stat().st_size} bytes)")
                    ext = p.suffix.lower()
                    if ext in media_suffixes:
                        candidates.append(p)
                if not candidates:
                    for p in requested_paths:
                        try:
                            if p.is_file() and p.suffix.lower() in media_suffixes:
                                candidates.append(p)
                        except Exception:
                            continue
                if not candidates:
                    detail_lines = []
                    if last_attempt_note:
                        detail_lines.append(f"最近尝试: {last_attempt_note}")
                    if last_err:
                        err_text = strip_ansi(str(last_err))
                        if err_text:
                            detail_lines.append(f"上一次错误: {err_text}")
                        else:
                            detail_lines.append(f"上一次错误: <empty message>; type={last_err_type or type(last_err).__name__}; repr={repr(last_err)}")
                    if last_traceback_text:
                        trace_tail = "\n".join(last_traceback_text.strip().splitlines()[-12:])
                        detail_lines.append("异常堆栈(尾部):\n" + trace_tail)
                    if last_debug_lines:
                        debug_seen: set[str] = set()
                        debug_tail: list[str] = []
                        for item in reversed(last_debug_lines[-80:]):
                            k = item.strip().lower()
                            if not k or k in debug_seen:
                                continue
                            debug_seen.add(k)
                            debug_tail.append(item.strip())
                            if len(debug_tail) >= 12:
                                break
                        debug_tail.reverse()
                        tail = "\n".join(debug_tail)
                        detail_lines.append("调试日志(尾部):\n" + tail)
                    if temp_outputs:
                        detail_lines.append("临时目录文件:\n" + "\n".join(temp_outputs[:12]))
                    if requested_paths:
                        detail_lines.append("yt-dlp 报告的输出路径:\n" + "\n".join(str(p) for p in requested_paths[:12]))
                    if selected_audio_summary:
                        detail_lines.append("音频格式诊断:\n" + selected_audio_summary)
                    if cookie_debug_summary:
                        detail_lines.append("Cookies 运行时诊断:\n" + cookie_debug_summary)
                    detail_lines.append("Cookies 传参诊断:\n" + cookie_runtime_hint)
                    detail_lines.append("运行版本诊断:\n" + runtime_version_summary)
                    detail_text = "\n".join(detail_lines)
                    if last_err and str(last_err).strip().startswith("未下载到音频文件"):
                        pass
                    elif detail_text:
                        last_err = RuntimeError("未下载到音频文件（可能被限制或链接无效）。\n" + detail_text)
                    else:
                        last_err = RuntimeError("未下载到音频文件（可能被限制或链接无效）。")
                    continue
                audio = max(candidates, key=lambda x: x.stat().st_size)
                cached_audio = None
                
                # 记录下载耗时
                download_duration = time.time() - start_time
                if status_callback: 
                    status_callback(f"Download finished in {download_duration:.1f}s. Audio extracted. Starting Whisper transcription...")
                
                if cache_path:
                    try:
                        if (not cache_path.exists()) or (cache_path.stat().st_size < audio.stat().st_size):
                            shutil.copy2(audio, cache_path)
                        if cache_path.exists() and cache_path.stat().st_size > 16 * 1024:
                            cached_audio = cache_path
                    except Exception:
                        cached_audio = None
                
                force_cpu_flag = bool(getattr(transcribe_video_audio_with_ytdlp, "_force_cpu", False))
                audio_path = str(cached_audio or audio)
                
                t_transcribe_start = time.time()
                text = transcribe_audio_with_whisper(audio_path, model_name=model_name, language=language, proxy_url=proxy_url, status_callback=status_callback, fast_mode=fast_mode, force_cpu=force_cpu_flag)
                transcribe_duration = time.time() - t_transcribe_start
                
                # 将耗时信息注入到 text 末尾的注释中，供 UI 解析
                timing_tag = f"<!-- TIMING: download={download_duration:.1f}, transcribe={transcribe_duration:.1f} -->"
                text += timing_tag
                
                label = f"{last_video_id or (cached_audio.stem if cached_audio else audio.stem)} | whisper:{(model_name or '').strip() or 'base'}"
                return label, text

        if last_err is not None:
            raise last_err
        if last_cookie_error:
            raise last_cookie_error
        raise RuntimeError("音频转写兜底失败（未知原因）。")


def fetch_available_models(api_key: str, base_url: str, proxy_url: str = None) -> list[str]:
    error_msg = ""
    # 1. 尝试使用 OpenAI SDK
    try:
        from openai import OpenAI
        import httpx
        
        client_kwargs = {"api_key": api_key}
        if base_url and base_url.strip():
            client_kwargs["base_url"] = base_url.strip()
        
        httpx_kwargs = {"verify": False}
        if proxy_url and proxy_url.strip():
            httpx_kwargs["proxy"] = proxy_url.strip()
        
        client_kwargs["http_client"] = httpx.Client(**httpx_kwargs)
        
        client = OpenAI(**client_kwargs)
        models_page = client.models.list()
        
        model_ids = []
        for m in models_page:
            if hasattr(m, "id"):
                model_ids.append(m.id)
            elif isinstance(m, dict):
                model_ids.append(m.get("id"))
                
        return sorted(model_ids)
    except Exception as e:
        error_msg = str(e)
    
    # 2. 如果 SDK 失败，尝试直接 Requests 请求 (兜底)
    try:
        import requests
        headers = {"Authorization": f"Bearer {api_key}"}
        
        target_url = base_url.strip()
        if not target_url.endswith("/"):
            target_url += "/"
        
        # 尝试猜测 models 端点
        if "v1" not in target_url:
            target_url += "v1/"
        target_url += "models"
        
        proxies = None
        if proxy_url and proxy_url.strip():
            proxies = {"http": proxy_url, "https": proxy_url}
            
        r = requests.get(target_url, headers=headers, proxies=proxies, verify=False, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        model_ids = []
        data_list = data.get("data", [])
        if isinstance(data_list, list):
            for m in data_list:
                if isinstance(m, dict):
                    model_ids.append(m.get("id"))
        
        if model_ids:
            # 简单过滤，排除 clearly non-chat models
            filtered = [
                m for m in model_ids 
                if not any(x in m for x in ["dall-e", "tts", "whisper", "embedding", "babbage", "davinci", "curie", "ada"])
            ]
            return sorted(filtered) if filtered else sorted(model_ids)
            
    except Exception as e2:
        error_msg += f" | Direct HTTP failed: {e2}"

    raise RuntimeError(f"获取模型列表失败: {error_msg}")

AUTHORITATIVE_SOURCE_RULES = [
    {
        "label": "乌克兰国防部官网",
        "url": "https://mod.gov.ua/en",
        "aliases": ["乌克兰国防部", "ukrainian ministry of defence", "ministry of defence of ukraine", "mod ukraine"],
    },
    {
        "label": "Defense News",
        "url": "https://www.defensenews.com/",
        "aliases": ["defense news", "defensenews"],
    },
    {
        "label": "斯洛伐克政府官网",
        "url": "https://www.vlada.gov.sk/en/",
        "aliases": ["斯洛伐克政府", "slovak government", "government of slovakia", "government office of the slovak republic"],
    },
    {
        "label": "斯洛伐克国防部官网",
        "url": "https://www.mosr.sk/mo-sr-en/",
        "aliases": ["斯洛伐克国防部", "slovak ministry of defense", "ministry of defense of the slovak republic"],
    },
    {
        "label": "塔斯社",
        "url": "https://tass.com/",
        "aliases": ["塔斯社", "tass"],
    },
    {
        "label": "美国国务院",
        "url": "https://www.state.gov/",
        "aliases": ["美国国务院", "u.s. department of state", "us department of state", "state department"],
    },
    {
        "label": "古巴外交部",
        "url": "https://cubaminrex.cu/en",
        "aliases": ["古巴外交部", "cuban ministry of foreign affairs", "ministry of foreign affairs of cuba", "cubaminrex"],
    },
    {
        "label": "匈牙利国家选举办公室",
        "url": "https://www.valasztas.hu/",
        "aliases": ["匈牙利国家选举办公室", "hungarian national election office", "national election office hungary", "valasztas"],
    },
    {
        "label": "UKMTO",
        "url": "https://www.ukmto.org/",
        "aliases": ["ukmto", "united kingdom maritime trade operations", "英国海事贸易行动中心"],
    },
    {
        "label": "彭博社",
        "url": "https://www.bloomberg.com/",
        "aliases": ["彭博社", "彭博", "bloomberg"],
    },
    {
        "label": "台湾证券交易所",
        "url": "https://www.twse.com.tw/en/",
        "aliases": ["台湾证券交易所", "台灣證券交易所", "台湾股市", "台灣股市", "twse", "taiwan stock exchange"],
    },
    {
        "label": "美丽岛电子报",
        "url": "https://www.my-formosa.com/",
        "aliases": ["美丽岛电子报", "美麗島電子報", "美丽岛", "美麗島", "my-formosa"],
    },
    {
        "label": "路透社",
        "url": "https://www.reuters.com/",
        "aliases": ["路透社", "reuters"],
    },
]


def _build_search_url(query: str, *, engine: str = "google", news: bool = False) -> str:
    """构造通用搜索链接，优先返回可人工复核的检索入口。"""
    encoded_q = quote(query)
    if engine == "bing":
        if news:
            return f"https://www.bing.com/news/search?q={encoded_q}"
        return f"https://www.bing.com/search?q={encoded_q}"
    if news:
        return f"https://www.google.com/search?tbm=nws&q={encoded_q}"
    return f"https://www.google.com/search?q={encoded_q}"


def _find_authoritative_sources(text: str) -> list[dict]:
    """根据文本中的机构名/媒体名匹配官网与权威媒体站点。"""
    haystack = str(text or "").lower()
    if not haystack:
        return []
    matched: list[dict] = []
    seen_urls: set[str] = set()
    for rule in AUTHORITATIVE_SOURCE_RULES:
        aliases = [str(alias or "").lower() for alias in rule.get("aliases", [])]
        if not any(alias and alias in haystack for alias in aliases):
            continue
        url = str(rule.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        matched.append(rule)
    return matched


def _extract_year_tokens(text: str) -> list[str]:
    """提取文本中的年份，用于约束强时效搜索。"""
    years = re.findall(r"\b(?:19|20)\d{2}\b", str(text or ""))
    deduped: list[str] = []
    seen: set[str] = set()
    for year in years:
        if year in seen:
            continue
        seen.add(year)
        deduped.append(year)
    return deduped


def _prepare_fact_check_queries(claim: str, queries: list[str] | None) -> list[str]:
    """为事实核查生成更精确的检索词，补充时间与站点限定。"""
    candidates: list[str] = []
    seen: set[str] = set()

    def add_query(value: str) -> None:
        query = re.sub(r"\s+", " ", str(value or "")).strip()
        if not query:
            return
        lowered = query.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        candidates.append(query)

    claim_text = str(claim or "").strip()
    add_query(claim_text)
    for item in queries or []:
        add_query(item)

    years = _extract_year_tokens(" ".join(candidates))
    authoritative_sources = _find_authoritative_sources(" ".join(candidates))

    for base_query in list(candidates):
        if re.search(r"(大选|选举|election)", base_query, re.I):
            add_query(f"{base_query} 官方结果")
            add_query(f"{base_query} official result")
        if re.search(r"(声明|通报|公告|会谈|访问|statement|announcement|meeting|visit)", base_query, re.I):
            add_query(f"{base_query} 官方声明")
            add_query(f"{base_query} official statement")
        if re.search(r"(国防部|外交部|政府|minister|ministry|government)", base_query, re.I):
            add_query(f"{base_query} 官网")

        for year in years[:2]:
            if year not in base_query:
                add_query(f"{base_query} {year}")

        for source in authoritative_sources[:3]:
            source_url = str(source.get("url") or "").strip()
            domain = urlparse(source_url).netloc
            if domain:
                add_query(f"site:{domain} {base_query}")

    return candidates[:8]


def perform_web_search(queries: list[str], proxy: str = None) -> str:
    if not queries:
        return ""

    results_text = []
    global_source_links: list[str] = []
    seen_source_urls: set[str] = set()

    # 事实核查统一收敛为可人工复核的 Google/Bing 新闻检索入口，
    # 同时附上已识别到的官网/权威媒体站点，避免模型只输出模糊机构名。
    def add_search_links(q_term: str) -> None:
        try:
            results_text.append(f"### 搜索关键字: {q_term}")
            results_text.append(f"- [Google 新闻核查]({_build_search_url(q_term, engine='google', news=True)})")
            results_text.append(f"- [Google 网页核查]({_build_search_url(q_term, engine='google', news=False)})")
            results_text.append(f"- [Bing 新闻核查]({_build_search_url(q_term, engine='bing', news=True)})")
            results_text.append(f"- [Bing 网页核查]({_build_search_url(q_term, engine='bing', news=False)})")

            matched_sources = _find_authoritative_sources(q_term)
            if matched_sources:
                results_text.append("- 权威站点参考：")
                for source in matched_sources[:4]:
                    label = str(source.get("label") or "").strip()
                    url = str(source.get("url") or "").strip()
                    if not label or not url:
                        continue
                    results_text.append(f"  - [{label}]({url})")
                    if url not in seen_source_urls:
                        seen_source_urls.add(url)
                        global_source_links.append(f"- [{label}]({url})")
                    domain = urlparse(url).netloc
                    if domain:
                        site_query = f"site:{domain} {q_term}"
                        results_text.append(f"  - [{label} 定向搜索]({_build_search_url(site_query, engine='google', news=True)})")
            results_text.append("")
        except Exception:
            pass

    for q in queries:
        add_search_links(q)

    if global_source_links:
        results_text.append("### 已识别的权威站点")
        results_text.extend(global_source_links[:8])
        results_text.append("")

    return "\n".join(results_text)


def _extract_json_candidate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _extract_json_string_field(raw_text: str, field_names: list[str]) -> str:
    raw_text = raw_text or ""
    for field_name in field_names:
        pattern = rf'"{re.escape(field_name)}"\s*:\s*("(?:\\.|[^"\\])*")'
        match = re.search(pattern, raw_text, re.S)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
            return str(value or "").strip()
        except Exception:
            continue
    return ""


def _parse_summary_payload(raw_text: str):
    visited = set()
    candidates = [raw_text, _extract_json_candidate(raw_text)]
    while candidates:
        candidate = (candidates.pop(0) or "").strip()
        if not candidate or candidate in visited:
            continue
        visited.add(candidate)
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, str):
            candidates.append(data)
            candidates.append(_extract_json_candidate(data))
            continue
        if isinstance(data, dict):
            return data
    summary_md = _extract_json_string_field(raw_text, ["summary_markdown", "summary", "summary_md"])
    fact_md = _extract_json_string_field(raw_text, ["fact_check_markdown", "fact_check", "factcheck_markdown", "fact_check_md"])
    if summary_md:
        return {
            "summary_markdown": summary_md,
            "fact_check_markdown": fact_md,
        }
    return None


def _normalize_summary_payload(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    summary_text = (
        payload.get("summary_markdown")
        or payload.get("summary")
        or payload.get("summary_md")
        or ""
    )
    fact_check_text = (
        payload.get("fact_check_markdown")
        or payload.get("fact_check")
        or payload.get("factcheck_markdown")
        or payload.get("fact_check_md")
        or ""
    )
    summary_text = str(summary_text or "").strip()
    fact_check_text = str(fact_check_text or "").strip()
    if not summary_text:
        return None
    if not fact_check_text:
        fact_check_text = "- 暂未成功生成结构化事实核查结果，请重新尝试生成。"
    return {
        "summary_markdown": summary_text,
        "fact_check_markdown": fact_check_text,
    }


def _is_placeholder_fact_check(text: str) -> bool:
    """判断事实核查内容是否仍是空洞占位文案。"""
    value = str(text or "").strip()
    if not value:
        return True
    placeholder_markers = [
        "暂未成功生成结构化事实核查结果",
        "未成功拆出结构化事实核查结果",
        "AI 未能稳定输出结构化事实核查结果",
        "模型未返回事实核查结果",
    ]
    return any(marker in value for marker in placeholder_markers)


def _extract_markdown_links(markdown_text: str) -> list[tuple[str, str]]:
    text = str(markdown_text or "")
    if not text:
        return []
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        clean_label = label.strip()
        clean_url = url.strip()
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        pairs.append((clean_label or clean_url, clean_url))
    return pairs


def _soften_fact_check_wording(text: str) -> str:
    value = str(text or "")
    if not value:
        return value
    replacements = [
        (r"手动搜索未发现", "当前检索到的公开候选来源暂未形成直接佐证"),
        (r"未发现支持", "暂缺可直接支撑"),
        (r"未搜索到关于", "当前检索到的公开候选来源中，暂缺关于"),
        (r"未搜索到来自", "当前检索到的公开候选来源中，暂缺来自"),
        (r"未检索到可靠外部来源", "当前可交叉验证的公开候选来源仍不足"),
        (r"未找到关于", "当前检索到的公开候选来源中，暂缺关于"),
        (r"未找到来自", "当前检索到的公开候选来源中，暂缺来自"),
        (r"未发现关于", "当前检索到的公开候选来源中，暂缺关于"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return value


def _soften_absolute_negative_fact_check_with_sources(
    text: str,
    source_links: list[tuple[str, str]] | None,
) -> str:
    """当条目里已附带候选来源链接时，避免保留“未发现任何报道”这类绝对否定表述。"""
    value = str(text or "")
    if not value or not source_links:
        return value

    link_text = " ".join(f"{label} {url}" for label, url in source_links).lower()
    has_news_evidence = any(
        token in link_text
        for token in [
            "reuters",
            "路透",
            "bloomberg",
            "彭博",
            "twse",
            "taiwan stock exchange",
            "台灣證券交易所",
            "台湾证券交易所",
            "my-formosa",
            "美麗島",
            "美丽岛",
        ]
    )
    if not has_news_evidence:
        return value

    replacements = [
        (
            r"未发现任何主流财经新闻媒体[^。\n]*",
            "当前候选来源已包含主流财经媒体或权威站点链接，不宜直接下结论为“未发现报道”，应以这些链接的具体内容为准",
        ),
        (
            r"未发现来自[^。\n]*的报道",
            "当前候选来源已提供可进一步核对的相关报道或权威站点链接，不宜直接下结论为“未发现报道”",
        ),
        (
            r"未发现[^。\n]*证明",
            "当前候选来源已提供可进一步核对的相关链接，请直接依据链接内容判断是否构成证明",
        ),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return value


def _enrich_fact_check_markdown_with_links(fact_md: str, search_results_md: str) -> str:
    fact_text = str(fact_md or "").strip()
    if not fact_text:
        return fact_text
    search_links = _extract_markdown_links(search_results_md)
    if not search_links:
        return _soften_fact_check_wording(fact_text)
    return _enrich_fact_check_items_with_claim_sources(
        fact_text,
        [{"search_markdown": search_results_md}],
    )


def _enrich_fact_check_items_with_claim_sources(fact_md: str, claim_sources: list[dict] | None) -> str:
    fact_text = str(fact_md or "").strip()
    if not fact_text:
        return fact_text
    if not claim_sources:
        return fact_text

    # 兼容两种常见输出：
    # 1. `### 条目1` 这种结构化块
    # 2. `1. 新闻/声明：...` 这种编号列表
    sections = re.split(
        r"(?=^(?:###\s*条目\d+|\d+\.\s*(?:新闻/声明|关键声明|声明|新闻)[:：]))",
        _soften_fact_check_wording(fact_text),
        flags=re.M,
    )
    updated_sections: list[str] = []
    claim_idx = 0

    for section in sections:
        stripped = section.strip()
        if not stripped:
            continue
        is_structured_item = bool(
            re.match(r"^(?:###\s*条目\d+|\d+\.\s*(?:新闻/声明|关键声明|声明|新闻)[:：])", stripped)
        )
        if not is_structured_item:
            updated_sections.append(stripped)
            continue

        if len(claim_sources) == 1:
            current_sources = claim_sources[0]
        else:
            current_sources = claim_sources[claim_idx] if claim_idx < len(claim_sources) else {}
            claim_idx += 1
        source_links = _extract_markdown_links(str(current_sources.get("search_markdown") or ""))
        if not source_links:
            updated_sections.append(stripped)
            continue

        if re.search(r"\[[^\]]+\]\(https?://", stripped):
            updated_sections.append(stripped)
            continue

        source_text = "；".join(f"[{label}]({url})" for label, url in source_links[:3])
        stripped = _soften_absolute_negative_fact_check_with_sources(stripped, source_links)

        # 如果模型已经输出了“来源/出处”但没有链接，保留原有文字说明并额外补一行可点击链接。
        if re.search(r"来源/出处[:：]", stripped):
            stripped = re.sub(
                r"(来源/出处[:：][^\n]*)",
                lambda m: f"{m.group(1)}\n- 来源链接： {source_text}",
                stripped,
                count=1,
            )
        else:
            stripped = stripped.rstrip() + f"\n- 来源/出处： {source_text}"
        updated_sections.append(stripped)

    return "\n\n".join(updated_sections)


def _build_fact_check_fallback_markdown(
    *,
    claim_sources: list[dict] | None = None,
    search_results_md: str = "",
) -> str:
    """在模型未稳定输出时，基于候选来源生成最小可用的事实核查稿。"""
    sections = [
        "### 条目1",
        "- 新闻/声明：系统已先整理出本条可核查说法，并附上可直接复核的候选来源线索。",
        "- 核查结论：当前证据仍需继续补充",
        "- 依据：本条先展示系统已汇总的搜索入口和权威站点，方便快速继续核对，不作为最终定论。",
        "- 待补充核查点：建议优先核对原始报道时间、数字口径、机构原文和二次转载是否存在偏差。",
    ]

    if claim_sources:
        rendered_sections: list[str] = []
        for idx, item in enumerate(claim_sources, start=1):
            claim = str(item.get("claim") or f"候选声明{idx}").strip()
            query_list = item.get("queries") or []
            search_md = str(item.get("search_markdown") or "")
            links = _extract_markdown_links(search_md)
            source_text = "；".join(f"[{label}]({url})" for label, url in links[:5]) if links else "当前未提取到可点击来源链接。"
            search_text = " | ".join(str(query).strip() for query in query_list if str(query).strip()) or "未生成搜索词"
            rendered_sections.append(
                "\n".join(
                    [
                        f"### 条目{idx}",
                        f"- 新闻/声明：{claim}",
                        "- 核查结论：当前证据仍需继续补充",
                        f"- 依据：系统已先保留候选搜索词 `{search_text}` 与可人工复核来源，便于继续核对；本条内容不直接作为最终定论。",
                        "- 待补充核查点：建议继续核对原始报道、官方披露、统计口径与发布时间是否一致。",
                        f"- 来源/出处： {source_text}",
                    ]
                )
            )
        if rendered_sections:
            return "\n\n".join(rendered_sections)

    search_links = _extract_markdown_links(search_results_md)
    if search_links:
        source_text = "；".join(f"[{label}]({url})" for label, url in search_links[:8])
        sections.append(f"- 来源/出处： {source_text}")
    else:
        sections.append("- 来源/出处：当前未提取到可点击来源链接。")
    return "\n".join(sections)


SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".pptx"}
DEFAULT_DOCUMENT_MAX_MB = int(os.environ.get("DOCUMENT_MAX_UPLOAD_MB", "20") or "20")
DEFAULT_DOCUMENT_DIRECT_SUMMARY_CHARS = int(os.environ.get("DOCUMENT_DIRECT_SUMMARY_CHARS", "15000") or "15000")
DEFAULT_DOCUMENT_CHUNK_CHARS = int(os.environ.get("DOCUMENT_CHUNK_CHARS", "12000") or "12000")


def validate_document_upload(file_name: str, file_size: int, max_size_mb: int = DEFAULT_DOCUMENT_MAX_MB) -> tuple[bool, str]:
    file_name = str(file_name or "").strip()
    suffix = os.path.splitext(file_name)[1].lower()
    if not file_name or suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        return False, f"暂不支持该文档格式。当前支持：{supported}"
    if int(file_size or 0) <= 0:
        return False, "上传文件为空，请重新选择。"
    if int(file_size or 0) > max_size_mb * 1024 * 1024:
        return False, f"文档超过大小限制（{max_size_mb}MB），请拆分后再上传。"
    return True, ""


def clean_document_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    blank_pending = False
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if not blank_pending:
                lines.append("")
                blank_pending = True
            continue
        blank_pending = False
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _extract_pdf_text(file_bytes: bytes) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("未安装 pypdf，无法解析 PDF。") from e

    reader = PdfReader(BytesIO(file_bytes))
    page_texts = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            page_text = str(page.extract_text() or "").strip()
        except Exception:
            page_text = ""
        if page_text:
            page_texts.append(f"## 第{idx}页\n{page_text}")
    raw_text = "\n\n".join(page_texts).strip()
    ocr_used = False
    if not raw_text:
        ocr_text = _extract_pdf_text_via_ocr(file_bytes)
        if ocr_text:
            raw_text = ocr_text
            ocr_used = True

    return {
        "raw_text": raw_text,
        "page_count": len(reader.pages),
        "section_count": len(page_texts),
        "ocr_used": ocr_used,
    }


def _extract_docx_text(file_bytes: bytes) -> dict:
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("未安装 python-docx，无法解析 DOCX。") from e

    document = Document(BytesIO(file_bytes))
    parts = []
    paragraph_count = 0
    for para in document.paragraphs:
        text = str(para.text or "").strip()
        if not text:
            continue
        paragraph_count += 1
        style_name = str(getattr(getattr(para, "style", None), "name", "") or "").lower()
        heading_match = re.search(r"heading\s*(\d+)", style_name)
        if heading_match:
            level = max(1, min(6, int(heading_match.group(1))))
            parts.append(f"{'#' * level} {text}")
        else:
            parts.append(text)

    table_count = 0
    for table in document.tables:
        rows = []
        for row in table.rows:
            cells = [str(cell.text or "").strip() for cell in row.cells]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            table_count += 1
            parts.append(f"## 表格{table_count}\n" + "\n".join(rows))

    return {
        "raw_text": "\n\n".join(parts).strip(),
        "page_count": None,
        "section_count": paragraph_count + table_count,
    }


def _extract_pptx_text(file_bytes: bytes) -> dict:
    try:
        from pptx import Presentation
    except ImportError as e:
        raise RuntimeError("未安装 python-pptx，无法解析 PPTX。") from e

    prs = Presentation(BytesIO(file_bytes))
    slide_parts = []
    for idx, slide in enumerate(prs.slides, start=1):
        shape_texts = []
        for shape in slide.shapes:
            text = str(getattr(shape, "text", "") or "").strip()
            if text:
                shape_texts.append(text)
                continue
            table = getattr(shape, "table", None)
            if table:
                rows = []
                for row in table.rows:
                    cells = [str(cell.text or "").strip() for cell in row.cells]
                    cells = [cell for cell in cells if cell]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    shape_texts.append("\n".join(rows))
        if shape_texts:
            slide_parts.append(f"## 第{idx}页幻灯片\n" + "\n\n".join(shape_texts))

    return {
        "raw_text": "\n\n".join(slide_parts).strip(),
        "page_count": len(prs.slides),
        "section_count": len(slide_parts),
    }


def _extract_plain_text(file_bytes: bytes) -> dict:
    encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "latin-1"]
    last_error = None
    for encoding in encodings:
        try:
            return {
                "raw_text": file_bytes.decode(encoding).strip(),
                "page_count": None,
                "section_count": None,
            }
        except Exception as e:
            last_error = e
    raise RuntimeError(f"文本文件解码失败：{last_error}")


def _extract_pdf_text_via_ocr(file_bytes: bytes) -> str:
    if str(os.environ.get("DOCUMENT_PDF_OCR_ENABLED", "1") or "1").strip().lower() in {"0", "false", "no"}:
        return ""
    try:
        import fitz
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""

    try:
        ocr_engine = RapidOCR()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_texts = []
        max_pages = int(os.environ.get("DOCUMENT_PDF_OCR_MAX_PAGES", "20") or "20")
        for idx, page in enumerate(doc, start=1):
            if idx > max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            channels = 3 if pix.n >= 3 else 1
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if channels == 1:
                img = img[:, :, 0]
            elif pix.n > 3:
                img = img[:, :, :3]
            result, _ = ocr_engine(img)
            if not result:
                continue
            page_lines = []
            for item in result:
                try:
                    text = str(item[1] or "").strip()
                except Exception:
                    text = ""
                if text:
                    page_lines.append(text)
            if page_lines:
                page_texts.append(f"## 第{idx}页\n" + "\n".join(page_lines))
        return "\n\n".join(page_texts).strip()
    except Exception as e:
        print(f"PDF OCR extraction failed: {e}")
        return ""


def _guess_remote_file_name(url: str, response=None) -> str:
    parsed = urlparse(str(url or "").strip())
    candidate = os.path.basename(parsed.path or "").strip()
    if candidate:
        return candidate
    content_type = str(getattr(response, "headers", {}).get("Content-Type", "") or "").lower()
    if "pdf" in content_type:
        return "remote.pdf"
    if "presentation" in content_type or "pptx" in content_type:
        return "remote.pptx"
    if "wordprocessingml" in content_type or "docx" in content_type:
        return "remote.docx"
    if "markdown" in content_type:
        return "remote.md"
    if "text/plain" in content_type:
        return "remote.txt"
    return "remote.html"


def _build_requests_kwargs(proxy_url: str = None, timeout_seconds: float = 25.0) -> dict:
    kwargs = {"timeout": timeout_seconds, "verify": False}
    if proxy_url and proxy_url.strip():
        kwargs["proxies"] = {
            "http": proxy_url.strip(),
            "https": proxy_url.strip(),
        }
    return kwargs


def _build_article_headers(url: str) -> dict:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if "mp.weixin.qq.com" in host:
        headers.update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40",
            "Referer": "https://mp.weixin.qq.com/",
        })
    return headers


def _looks_like_access_block_page(html: str, url: str = "") -> bool:
    sample = str(html or "")[:4000]
    host = (urlparse(str(url or "").strip()).netloc or "").lower()
    keywords = [
        "环境异常",
        "去验证",
        "请在微信客户端打开链接",
        "访问过于频繁",
        "当前访问环境异常",
        "完成验证",
    ]
    if any(keyword in sample for keyword in keywords):
        return True
    if "mp.weixin.qq.com" in host and "#js_content" not in sample and "js_content" not in sample:
        return True
    return False


def _extract_wechat_article_text(html: str, url: str) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise RuntimeError("未安装 beautifulsoup4，无法解析微信公众号文章。") from e

    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("#activity-name") or soup.select_one("h1")
    meta_title = soup.select_one('meta[property="og:title"]')
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not title and meta_title:
        title = str(meta_title.get("content") or "").strip()

    content_node = soup.select_one("#js_content")
    if not content_node:
        raise RuntimeError("未能从微信公众号页面中定位正文区域。")

    for tag in content_node.select("script, style, noscript"):
        tag.decompose()
    raw_text = content_node.get_text("\n", strip=True)
    clean_text = clean_document_text(raw_text)
    if not clean_text or len(clean_text) < 80:
        raise RuntimeError("微信公众号正文提取结果过短，疑似仍为异常页。")
    if title and title not in clean_text[:150]:
        raw_text = f"# {title}\n\n{raw_text}".strip()
        clean_text = clean_document_text(raw_text)

    return {
        "file_name": title or "wechat_article.html",
        "file_type": "html",
        "raw_text": raw_text,
        "clean_text": clean_text,
        "char_count": len(clean_text),
        "page_count": None,
        "section_count": None,
        "source_url": url,
        "ocr_used": False,
    }


def extract_web_article_text(url: str, proxy_url: str = None) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise RuntimeError("未安装 beautifulsoup4，无法解析网页文章。") from e

    headers = _build_article_headers(url)
    resp = requests.get(url, headers=headers, **_build_requests_kwargs(proxy_url, timeout_seconds=30.0))
    resp.raise_for_status()
    html = resp.text
    if "mp.weixin.qq.com" in (urlparse(url).netloc or "").lower():
        return _extract_wechat_article_text(html, url)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = []
    for node in main.find_all(["h1", "h2", "h3", "p", "li"], limit=500):
        text = node.get_text(" ", strip=True)
        if not text or len(text) < 2:
            continue
        if node.name in {"h1", "h2", "h3"}:
            level = {"h1": "#", "h2": "##", "h3": "###"}.get(node.name, "##")
            blocks.append(f"{level} {text}")
        else:
            blocks.append(text)

    raw_text = "\n\n".join(blocks).strip()
    if title and title not in raw_text[:200]:
        raw_text = f"# {title}\n\n{raw_text}".strip()
    clean_text = clean_document_text(raw_text)
    if not clean_text or _looks_like_access_block_page(html, url):
        raise RuntimeError("网页未提取到足够正文内容，请尝试更换文章链接。")
    return {
        "file_name": title or _guess_remote_file_name(url, resp) or "remote_article.html",
        "file_type": "html",
        "raw_text": raw_text,
        "clean_text": clean_text,
        "char_count": len(clean_text),
        "page_count": None,
        "section_count": None,
        "source_url": url,
        "ocr_used": False,
    }


def extract_document_from_url(url: str, proxy_url: str = None) -> dict:
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("请输入完整的在线链接（以 http:// 或 https:// 开头）。")

    headers = _build_article_headers(url)
    resp = requests.get(url, stream=True, headers=headers, **_build_requests_kwargs(proxy_url, timeout_seconds=35.0))
    resp.raise_for_status()
    content = resp.content
    file_name = _guess_remote_file_name(url, resp)
    suffix = os.path.splitext(file_name)[1].lower()
    content_type = str(resp.headers.get("Content-Type", "") or "").lower()

    if not suffix:
        if "pdf" in content_type:
            file_name = "remote.pdf"
        elif "presentation" in content_type or "pptx" in content_type:
            file_name = "remote.pptx"
        elif "wordprocessingml" in content_type or "docx" in content_type:
            file_name = "remote.docx"
        elif "markdown" in content_type:
            file_name = "remote.md"
        elif "text/plain" in content_type:
            file_name = "remote.txt"
        else:
            file_name = "remote_article.html"
        suffix = os.path.splitext(file_name)[1].lower()

    if suffix in SUPPORTED_DOCUMENT_EXTENSIONS:
        ok, err = validate_document_upload(file_name, len(content))
        if not ok:
            raise RuntimeError(err)
        result = extract_document_text(content, file_name)
        result["source_url"] = url
        return result

    return extract_web_article_text(url, proxy_url=proxy_url)


def extract_document_text(file_bytes: bytes, file_name: str) -> dict:
    suffix = os.path.splitext(str(file_name or "").strip())[1].lower()
    if suffix == ".pdf":
        extracted = _extract_pdf_text(file_bytes)
    elif suffix == ".docx":
        extracted = _extract_docx_text(file_bytes)
    elif suffix == ".pptx":
        extracted = _extract_pptx_text(file_bytes)
    else:
        extracted = _extract_plain_text(file_bytes)

    raw_text = str(extracted.get("raw_text") or "").strip()
    clean_text = clean_document_text(raw_text)
    if not clean_text:
        raise RuntimeError("文档未提取到可用文本，请确认文档不是纯扫描图片，或先转换为可复制文本。")

    return {
        "file_name": file_name,
        "file_type": suffix.lstrip("."),
        "raw_text": raw_text,
        "clean_text": clean_text,
        "char_count": len(clean_text),
        "page_count": extracted.get("page_count"),
        "section_count": extracted.get("section_count"),
        "ocr_used": bool(extracted.get("ocr_used", False)),
    }


def split_document_chunks(text: str, max_chars: int = DEFAULT_DOCUMENT_CHUNK_CHARS) -> list[dict]:
    text = clean_document_text(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks = []
    current_parts = []
    current_len = 0

    def flush_current():
        nonlocal current_parts, current_len
        if not current_parts:
            return
        chunk_text = "\n\n".join(current_parts).strip()
        chunks.append({
            "chunk_index": len(chunks) + 1,
            "text": chunk_text,
            "char_count": len(chunk_text),
        })
        current_parts = []
        current_len = 0

    for para in paragraphs:
        if len(para) > max_chars:
            flush_current()
            start = 0
            while start < len(para):
                end = min(start + max_chars, len(para))
                split_at = para.rfind("。", start, end)
                if split_at <= start + int(max_chars * 0.6):
                    split_at = para.rfind("，", start, end)
                if split_at <= start + int(max_chars * 0.5):
                    split_at = end
                else:
                    split_at += 1
                piece = para[start:split_at].strip()
                if piece:
                    chunks.append({
                        "chunk_index": len(chunks) + 1,
                        "text": piece,
                        "char_count": len(piece),
                    })
                start = split_at
            continue

        para_len = len(para) + 2
        if current_parts and current_len + para_len > max_chars:
            flush_current()
        current_parts.append(para)
        current_len += para_len

    flush_current()
    return chunks


def _build_openai_client(api_key: str, base_url: str, proxy_url: str = None):
    if not api_key:
        raise RuntimeError("请填写 API Key 以启用总结功能。")
    try:
        from openai import OpenAI
        import httpx
    except ImportError as e:
        raise RuntimeError("未安装 openai 依赖，无法进行总结。") from e

    client_kwargs = {"api_key": api_key}
    if base_url and base_url.strip():
        client_kwargs["base_url"] = base_url.strip()

    httpx_kwargs = {"verify": False}
    if proxy_url and proxy_url.strip():
        httpx_kwargs["proxy"] = proxy_url.strip()
    client_kwargs["http_client"] = httpx.Client(**httpx_kwargs)
    return OpenAI(**client_kwargs)


def _extract_completion_content(raw_resp) -> str:
    if isinstance(raw_resp, dict):
        choices = raw_resp.get("choices", [])
        if choices:
            return str(choices[0].get("message", {}).get("content", "") or "")
        return ""
    if hasattr(raw_resp, "choices") and raw_resp.choices:
        return str(raw_resp.choices[0].message.content or "")
    if isinstance(raw_resp, str):
        return raw_resp
    return ""


def _extract_summary_markdown(raw_text: str) -> str:
    payload = _parse_summary_payload(raw_text)
    if isinstance(payload, dict):
        summary_text = str(
            payload.get("summary_markdown")
            or payload.get("summary")
            or payload.get("summary_md")
            or ""
        ).strip()
        if summary_text:
            return summary_text
    return str(raw_text or "").strip()


def _summarize_document_passage(client, model: str, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    response = client.chat.completions.create(
        model=model.strip() or "gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    content = _extract_completion_content(response)
    if not content:
        raise RuntimeError("模型未返回有效总结内容。")
    return _extract_summary_markdown(content)


def summarize_document_text(
    text: str,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str = None,
    progress_callback=None,
) -> dict:
    cleaned_text = clean_document_text(text)
    if not cleaned_text:
        raise RuntimeError("文档文本为空，无法总结。")

    client = _build_openai_client(api_key, base_url, proxy_url)
    content_len = len(cleaned_text)
    direct_system_prompt = (
        "你是一个专业的文档总结助手。请始终返回合法 JSON，且只能包含字段 `summary_markdown`。"
        "输出必须使用 Markdown，结构固定为：`## 核心主题`、`## 主要内容`、`## 关键信息`、`## 结论（可选）`。"
        "所有内容尽量分条列出，不要写成长篇大段落。"
    )

    if content_len <= DEFAULT_DOCUMENT_DIRECT_SUMMARY_CHARS:
        if callable(progress_callback):
            progress_callback(35, "文档较短，正在直接生成总结...")
        prompt = (
            "请总结以下文档内容。\n"
            "要求：\n"
            "- 只返回 JSON\n"
            "- 仅包含字段 `summary_markdown`\n"
            "- `## 主要内容` 中输出 6-10 条要点\n"
            "- `## 结论（可选）` 只有在文档确实有明确结论时才输出\n\n"
            f"文档正文：\n{cleaned_text}"
        )
        summary_markdown = _summarize_document_passage(
            client,
            model,
            direct_system_prompt,
            prompt,
            max_tokens=2200,
        )
        if callable(progress_callback):
            progress_callback(100, "文档总结完成。")
        return {
            "summary_markdown": summary_markdown,
            "strategy": "direct",
            "chunk_count": 1,
            "char_count": content_len,
        }

    chunks = split_document_chunks(cleaned_text, max_chars=DEFAULT_DOCUMENT_CHUNK_CHARS)
    if not chunks:
        raise RuntimeError("文档分块失败，无法继续总结。")

    chunk_summaries = []
    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        if callable(progress_callback):
            progress_callback(20 + int(50 * idx / max(1, total_chunks)), f"正在总结第 {idx}/{total_chunks} 块...")
        chunk_prompt = (
            f"请总结下面这段文档片段（第 {idx}/{total_chunks} 块）。\n"
            "要求：\n"
            "- 只返回 JSON\n"
            "- 仅包含字段 `summary_markdown`\n"
            "- 输出结构：`### 本块要点`、`### 本块关键信息`\n"
            "- 使用分条要点，不要长段落\n\n"
            f"文档片段：\n{chunk['text']}"
        )
        chunk_summary = _summarize_document_passage(
            client,
            model,
            "你是一个文档片段总结助手。请始终返回合法 JSON，且只能包含 `summary_markdown`。",
            chunk_prompt,
            max_tokens=1000,
        )
        chunk_summaries.append(f"## 第{idx}块摘要\n{chunk_summary}")

    if callable(progress_callback):
        progress_callback(80, "正在汇总整份文档摘要...")
    merged_chunk_text = "\n\n".join(chunk_summaries)
    merge_prompt = (
        "下面是同一份长文档的分块摘要，请基于这些分块摘要生成最终总结。\n"
        "要求：\n"
        "- 只返回 JSON\n"
        "- 仅包含字段 `summary_markdown`\n"
        "- 使用 Markdown\n"
        "- 固定结构：`## 核心主题`、`## 主要内容`、`## 关键信息`、`## 结论（可选）`\n"
        "- `## 主要内容` 输出 8-12 条，按条列出\n"
        "- 不要重复每一块的相同意思\n\n"
        f"分块摘要：\n{merged_chunk_text}"
    )
    summary_markdown = _summarize_document_passage(
        client,
        model,
        direct_system_prompt,
        merge_prompt,
        max_tokens=2500,
    )
    if callable(progress_callback):
        progress_callback(100, "长文档总结完成。")
    return {
        "summary_markdown": summary_markdown,
        "strategy": "chunked",
        "chunk_count": total_chunks,
        "char_count": content_len,
    }


def _extract_claim_items(raw_text: str, max_claims: int) -> list[dict]:
    payload = _parse_summary_payload(raw_text)
    if isinstance(payload, dict):
        claim_list = payload.get("claims") or payload.get("items") or payload.get("key_claims") or []
    else:
        candidate = _extract_json_candidate(raw_text)
        try:
            parsed = json.loads(candidate)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            claim_list = parsed.get("claims") or parsed.get("items") or parsed.get("key_claims") or []
        else:
            claim_list = []

    normalized = []
    for item in claim_list:
        if isinstance(item, str):
            claim = item.strip()
            queries = [claim] if claim else []
        elif isinstance(item, dict):
            claim = str(item.get("claim") or item.get("statement") or item.get("text") or "").strip()
            queries = item.get("queries") or item.get("search_queries") or []
            if isinstance(queries, str):
                queries = [queries]
            queries = [str(q).strip() for q in queries if str(q).strip()]
        else:
            continue
        if claim:
            normalized.append({"claim": claim, "queries": queries[:2]})
        if len(normalized) >= max_claims:
            break
    return normalized


def extract_key_claims(
    text: str,
    summary_markdown: str,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str = None,
    max_claims: int = 8,
) -> list[dict]:
    client = _build_openai_client(api_key, base_url, proxy_url)
    cleaned_text = clean_document_text(text)
    excerpt = _build_fact_check_excerpt(cleaned_text, max_chars=7000)
    summary_excerpt = clean_document_text(summary_markdown or "")[:2200]
    prompt = (
        f"请从下面文档中提取最值得做事实核查的 {max_claims} 条关键声明。\n"
        "要求：\n"
        "- 只提取可核查的硬信息，不要提取纯观点、情绪表达或修辞。\n"
        "- 优先提取：数字、时间、政策、官方表述、事件是否发生、人物公开言论、强因果判断。\n"
        "- 如果原文里存在多条不同主体、不同数字、不同时间点的声明，不要合并成一条笼统表述。\n"
        "- 如果文本里可核查点较多，请尽量提满，不要只返回 1-2 条过于宽泛的声明。\n"
        "- 只返回 JSON，对象格式如下：\n"
        "{\n"
        '  "claims": [\n'
        '    {"claim": "声明内容", "queries": ["搜索词1", "搜索词2"]}\n'
        "  ]\n"
        "}\n"
        "- 每条 queries 最多给 2 个，搜索词中尽量包含主体、时间、地点、数字、机构。\n\n"
        f"文档总结：\n{summary_excerpt}\n\n"
        f"文档正文节选：\n{excerpt}"
    )
    response = client.chat.completions.create(
        model=model.strip() or "gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一个事实核查分析助手。请只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=1000,
        temperature=0.1,
    )
    content = _extract_completion_content(response)
    claims = _extract_claim_items(content, max_claims=max_claims)
    if not claims:
        raise RuntimeError("未能从文档中提取到可核查的关键声明。")
    return claims


def classify_document_for_fact_check(
    text: str,
    summary_markdown: str,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str = None,
) -> dict:
    client = _build_openai_client(api_key, base_url, proxy_url)
    cleaned_text = clean_document_text(text)
    excerpt = cleaned_text[:8000]
    prompt = (
        "请判断下面文档是否属于需要进行事实核查的类型。\n"
        "需要事实核查的典型类型包括：新闻、研究报告、时评/评论、政策解读、行业分析、带现实事件与数据结论的文章。\n"
        "通常不需要事实核查的类型包括：小说、散文、内部会议纪要、教程、产品文档、纯技术方案、个人笔记、合同草稿。\n"
        "请只返回 JSON，格式如下：\n"
        "{\n"
        '  "document_type": "news|research|commentary|policy_analysis|industry_analysis|meeting_notes|tutorial|technical_doc|fiction|personal_notes|other",\n'
        '  "should_fact_check": true,\n'
        '  "reason": "简短原因",\n'
        '  "recommended_claim_count": 5\n'
        "}\n"
        "- 如果文档明显属于新闻、研究、时评、政策解读、行业分析，should_fact_check 设为 true。\n"
        "- 否则设为 false。\n"
        "- recommended_claim_count 只能取 3、5、8 之一。\n\n"
        f"文档总结：\n{summary_markdown[:3500]}\n\n"
        f"文档正文节选：\n{excerpt}"
    )
    response = client.chat.completions.create(
        model=model.strip() or "gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一个文档类型判定助手。请只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        temperature=0.1,
    )
    content = _extract_completion_content(response)
    payload = _parse_summary_payload(content)
    if not isinstance(payload, dict):
        try:
            payload = json.loads(_extract_json_candidate(content))
        except Exception:
            payload = {}

    doc_type = str(payload.get("document_type") or "other").strip() or "other"
    should_fact_check = bool(payload.get("should_fact_check", False))
    reason = str(payload.get("reason") or "").strip()
    recommended_claim_count = int(payload.get("recommended_claim_count") or 5)
    if recommended_claim_count not in {3, 5, 8}:
        recommended_claim_count = 5

    if not reason:
        lowered = (summary_markdown + "\n" + excerpt).lower()
        if any(k in lowered for k in ["研究", "报告", "统计", "数据", "survey", "research", "report"]):
            doc_type = "research" if doc_type == "other" else doc_type
            should_fact_check = True
            reason = "文档包含研究/数据结论，适合做关键声明核查。"
        elif any(k in lowered for k in ["评论", "时评", "社论", "news", "记者", "新华社", "路透", "政策"]):
            doc_type = "commentary" if doc_type == "other" else doc_type
            should_fact_check = True
            reason = "文档涉及现实事件、新闻或政策判断，适合做关键声明核查。"
        else:
            reason = "文档更偏说明、教程、纪要或普通资料，可直接总结，无需默认核查。"

    return {
        "document_type": doc_type,
        "should_fact_check": should_fact_check,
        "reason": reason,
        "recommended_claim_count": recommended_claim_count,
    }


def _build_fact_check_excerpt(text: str, max_chars: int = 7000) -> str:
    cleaned = clean_document_text(text or "")
    if len(cleaned) <= max_chars:
        return cleaned
    head_chars = max(2500, int(max_chars * 0.72))
    tail_chars = max(800, max_chars - head_chars - 40)
    return (
        cleaned[:head_chars].rstrip()
        + "\n...(中间内容省略)...\n"
        + cleaned[-tail_chars:].lstrip()
    )


def decide_video_fact_check_plan(text: str, summary_markdown: str) -> dict:
    content = str(text or "").strip()
    summary = clean_document_text(summary_markdown or "")
    skip_fact_check, skip_reason = _should_skip_fact_check_for_video_text(content)
    if skip_fact_check:
        return {
            "should_fact_check": False,
            "reason": f"当前视频更像测试/演示/技术链路内容，已跳过新闻核查（{skip_reason}）。",
            "recommended_claim_count": 0,
        }

    excerpt = _build_fact_check_excerpt(content, max_chars=5000)
    combined = f"{summary}\n{excerpt}".lower()
    negative_markers = [
        "教程", "教学", "代码", "编程", "开发", "安装", "评测", "开箱",
        "软件使用", "产品演示", "课程", "训练营", "实操", "案例讲解",
    ]
    news_markers = [
        "新闻", "报道", "记者", "新华社", "央视", "路透", "彭博", "法新社",
        "government", "official", "breaking", "reported", "according to",
    ]
    event_markers = [
        "发布", "宣布", "通报", "回应", "发生", "遇袭", "逮捕", "起火", "坠毁",
        "停火", "制裁", "投票", "选举", "协议", "关税", "经济数据", "失业率",
        "cpi", "gdp", "policy", "tariff", "sanction", "election",
    ]
    hard_fact_patterns = [
        r"\b20\d{2}\b",
        r"\b\d+(?:\.\d+)?\s*%",
        r"\b\d+(?:,\d{3})+\b",
        r"\b\d+(?:\.\d+)?\s*(?:亿|万亿|万人|万例|亿美元|亿元|人)\b",
    ]
    negative_hits = sum(1 for marker in negative_markers if marker in combined)
    news_hits = sum(1 for marker in news_markers if marker in combined)
    event_hits = sum(1 for marker in event_markers if marker in combined)
    hard_fact_hits = sum(1 for pattern in hard_fact_patterns if re.search(pattern, combined))

    if negative_hits >= 2 and news_hits == 0 and event_hits == 0:
        return {
            "should_fact_check": False,
            "reason": "当前视频更像教程、产品演示或经验讲解，已默认跳过新闻核查。",
            "recommended_claim_count": 0,
        }

    should_fact_check = (
        (news_hits >= 1 and event_hits >= 1)
        or (event_hits >= 2 and hard_fact_hits >= 1)
        or (news_hits >= 2 and hard_fact_hits >= 1)
    )
    if not should_fact_check:
        return {
            "should_fact_check": False,
            "reason": "当前视频不够像新闻/事件型内容，已默认跳过新闻核查。",
            "recommended_claim_count": 0,
        }

    signal_score = news_hits + event_hits + hard_fact_hits
    recommended_claim_count = 5 if len(content) >= 9000 and signal_score >= 5 else 3
    return {
        "should_fact_check": True,
        "reason": "当前视频包含较明显的新闻/事件型声明，将只核查最关键的少量条目。",
        "recommended_claim_count": recommended_claim_count,
    }


def search_claim_sources(claim_items: list[dict], proxy_url: str = None) -> list[dict]:
    results = []
    for item in claim_items:
        claim = str(item.get("claim") or "").strip()
        queries = item.get("queries") or []
        if not queries:
            queries = [claim]
        prepared_queries = _prepare_fact_check_queries(claim, queries[:3])
        search_markdown = perform_web_search(prepared_queries, proxy=proxy_url)
        results.append({
            "claim": claim,
            "queries": prepared_queries,
            "search_markdown": search_markdown,
        })
    return results


def fact_check_document_claims(
    text: str,
    summary_markdown: str,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str = None,
    max_claims: int = 8,
    progress_callback=None,
) -> str:
    if max_claims <= 0:
        return ""

    summary_excerpt = clean_document_text(summary_markdown or "")[:2200]
    if callable(progress_callback):
        progress_callback(5, "正在抽取关键声明...")
    claims = extract_key_claims(
        text=text,
        summary_markdown=summary_excerpt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        proxy_url=proxy_url,
        max_claims=max_claims,
    )

    if callable(progress_callback):
        progress_callback(35, "正在检索外部来源...")
    claim_sources = search_claim_sources(claims, proxy_url=proxy_url)

    compiled_sections = []
    for idx, item in enumerate(claim_sources, start=1):
        search_excerpt = str(item.get("search_markdown") or "").strip()[:1200]
        compiled_sections.append(
            f"### 候选声明{idx}\n"
            f"- 声明：{item['claim']}\n"
            f"- 搜索词：{' | '.join(item.get('queries') or [])}\n"
            f"- 搜索结果：\n{search_excerpt}"
        )

    if callable(progress_callback):
        progress_callback(70, "正在生成逐条核查结果...")

    client = _build_openai_client(api_key, base_url, proxy_url)
    compiled_claim_text = "\n\n".join(compiled_sections)
    prompt = (
        "请根据下面的关键声明与搜索结果，输出逐条事实核查 Markdown。\n"
        "要求：\n"
        "- 每条都使用下面结构：\n"
        "### 条目1\n"
        "- 关键声明：...\n"
        "- 核查结论：属实 / 基本属实 / 存疑 / 缺乏证据 / 错误\n"
        "- 判断依据：\n"
        "  - 支持/对应的公开信息：...\n"
        "  - 冲突点或证据不足之处：...\n"
        "  - 当前判断原因：...\n"
        "- 待补充核查点：...\n"
        "- 来源/出处：给出 2-4 个外部来源链接，格式如 [新华社](https://...)\n"
        "- 如果原文包含多条不同声明，请分别成条输出，不要把多个数字或多个事件揉成一条。\n"
        "- 如果一条声明涉及数字、时间、机构、排名，请尽量分别说明这些要素是否匹配。\n"
        "- 如果判断依据里提到具体机构、政府部门、媒体名或官网名，优先附上该机构/媒体的官网或栏目页链接，不要只写机构名称。\n"
        "- 禁止把文档本身当来源。\n"
        "- 如果搜索结果不足，也要写明目前查到的候选来源，不要空着。\n"
        "- 避免使用“手动搜索未发现”“未搜索到”这类空泛表述，改为说明“现有公开候选来源不足以直接支撑该说法”，并保留候选链接。\n"
        "- 只返回 Markdown，不要 JSON。\n\n"
        f"文档总结：\n{summary_excerpt}\n\n"
        f"候选声明与搜索结果：\n{compiled_claim_text}"
    )
    response = client.chat.completions.create(
        model=model.strip() or "gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一个严谨的事实核查助手。请基于外部来源逐条核查关键声明。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2200,
        temperature=0.15,
    )
    content = _extract_completion_content(response).strip()
    if callable(progress_callback):
        progress_callback(100, "关键声明事实核查完成。")
    if not content:
        return _build_fact_check_fallback_markdown(claim_sources=claim_sources)
    final_markdown = _enrich_fact_check_items_with_claim_sources(content, claim_sources)
    if _is_placeholder_fact_check(final_markdown):
        return _build_fact_check_fallback_markdown(claim_sources=claim_sources)
    return final_markdown


def _should_skip_fact_check_for_video_text(text: str) -> tuple[bool, str]:
    """识别明显属于测试/产品说明/技术链路的字幕，避免误触发新闻事实核查。"""
    content = str(text or "").strip()
    if not content:
        return True, "empty_text"

    lowered = content.lower()
    strong_markers = [
        "模拟测试",
        "测试字幕",
        "测试文本",
        "回归验证",
        "链路验证",
        "产品主路径",
        "自动开始总结",
        "bridge payload",
        "payload_id",
        "ext_payload_id",
    ]
    if any(marker in content or marker in lowered for marker in strong_markers):
        return True, "strong_test_marker"

    paired_markers = [
        (("模拟", "测试"), "simulated_test_pair"),
        (("内部", "测试"), "internal_test_pair"),
        (("回归", "验证"), "regression_validation_pair"),
        (("技术", "链路"), "technical_pipeline_pair"),
        (("产品", "验证"), "product_validation_pair"),
    ]
    for keywords, reason in paired_markers:
        if all(keyword in content for keyword in keywords):
            return True, reason

    if re.search(r"(这是一次|这是一段|本次|用于).{0,24}(模拟|测试|验证|调试|演示)", content):
        return True, "intro_test_pattern"

    technical_markers = [
        "chrome插件",
        "render主站",
        "render",
        "bridge",
        "payload",
        "transcript",
        "api key",
        "自动总结",
        "主链路",
        "产品技术流程",
        "技术流程",
    ]
    technical_hits = sum(1 for marker in technical_markers if marker in lowered or marker in content)
    if technical_hits >= 3 and any(word in content for word in ["测试", "验证", "调试", "回归"]):
        return True, "technical_test_context"

    return False, ""


def summarize_text(
    text: str,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str = None,
    stream: bool = False,
    fact_check_model: str | None = None,
    enable_fact_check: bool = True,
):
    if not text or not text.strip():
        return "没有可总结的内容（文本为空）。"
    if not api_key:
        return "请填写 API Key 以启用总结功能。"

    if stream and str(fact_check_model or "").strip() and str(fact_check_model or "").strip() != str(model or "").strip():
        return "总结失败：当前双模型流水线不支持流式输出，请改用非流式模式。"

    try:
        client = _build_openai_client(api_key, base_url, proxy_url)
        summary_model = str(model or "").strip() or "gpt-3.5-turbo"
        fact_model = str(fact_check_model or "").strip() or summary_model

        content = text.strip()
        content_len = len(content)
        max_input_len = 16000 if content_len > 18000 else 20000
        if content_len > max_input_len:
            content = content[:max_input_len] + "\n...(内容过长已截断)..."

        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")

        fact_check_enabled = bool(enable_fact_check)
        if fact_check_enabled:
            skip_fact_check, skip_reason = _should_skip_fact_check_for_video_text(content)
            if skip_fact_check:
                fact_check_enabled = False
                print(f"SummarizeText: skip fact check, reason={skip_reason}", flush=True)
        else:
            print("SummarizeText: fact check disabled by caller", flush=True)

        prompt = (
            f"你是一个专业的视频内容总结助手。当前真实日期是：{current_date}。\n"
            "请总结以下视频字幕。\n"
            "【输出格式要求】\n"
            "请严格输出为 JSON 格式，且只能包含以下两个字段：`summary_markdown`、`fact_check_markdown`。\n"
            "1. `summary_markdown` 的要求：\n"
            "   - 必须是 Markdown。\n"
            "   - 必须按“逐条列点”的形式输出，不要写成长篇大段落。\n"
            "   - 固定结构如下：\n"
            "     ## 核心主题\n"
            "     - 1 句话概括视频主旨。\n"
            "     ## 主要内容\n"
            "     - 逐条列出 6-12 条要点。\n"
            "     - 每条只讲一个事实、观点或判断，语言清晰直接。\n"
            "     - 若某条是推测、判断、观点，请明确标注“视频观点”或“推测”。\n"
            "     ## 关键信息\n"
            "     - 列出数字、时间、人物、机构、政策名称等关键信息。\n"
            "     ## 结论（可选）\n"
            "     - 只有当视频确实提出了明确结论时才输出本节。\n"
            "     - 如果视频没有清晰结论，就不要硬写结论。\n"
            "2. `fact_check_markdown` 的要求：\n"
            "   - 必须返回空字符串 `\"\"`。\n"
            "   - 不要生成任何事实核查条目。\n\n"
            "**字幕内容输入：**\n"
            f"{content}"
        )
        max_tokens = 2600 if content_len < 12000 else 3000
        print(
            "SummarizeText: "
            f"content_len={content_len}, summary_model={summary_model}, fact_check_model={fact_model}, "
            f"fact_check_enabled={fact_check_enabled}"
        , flush=True)

        response = client.chat.completions.create(
            model=summary_model,
            messages=[
                {"role": "system", "content": "你是一个专业的视频内容总结助手。请始终返回合法 JSON。总结必须分条清晰。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            stream=stream,
        )
        if stream:
            return response

        content_str = _extract_completion_content(response)
        if not content_str:
            return f"总结失败：无法解析响应内容。\n原始响应: {str(response)[:500]}"

        normalized_payload = _normalize_summary_payload(_parse_summary_payload(content_str))
        if not normalized_payload:
            try:
                repair_prompt = (
                    "请将下面内容修复为合法 JSON，并且只能包含两个字段："
                    "`summary_markdown` 和 `fact_check_markdown`。\n"
                    "- `summary_markdown` 必须保留现有总结信息，并整理为清晰 Markdown。\n"
                    "- `fact_check_markdown` 必须返回空字符串，不要补任何事实核查内容。\n"
                    "- 只返回 JSON，不要解释。\n\n"
                    f"原始内容：\n{content_str}"
                )
                repair_resp = client.chat.completions.create(
                    model=summary_model,
                    messages=[
                        {"role": "system", "content": "你是一个 JSON 修复助手，只返回合法 JSON。"},
                        {"role": "user", "content": repair_prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=min(2200, max_tokens),
                    temperature=0.1,
                )
                repair_content = _extract_completion_content(repair_resp)
                normalized_payload = _normalize_summary_payload(_parse_summary_payload(repair_content))
            except Exception as repair_exc:
                print(f"Repair summary JSON failed: {repair_exc}", flush=True)

        if not normalized_payload:
            normalized_payload = {
                "summary_markdown": content_str,
                "fact_check_markdown": "",
            }

        summary_markdown = str(normalized_payload.get("summary_markdown") or "").strip() or content_str
        fact_check_markdown = ""
        if fact_check_enabled and len(content) > 100:
            try:
                max_claims = 8 if content_len >= 12000 else 6 if content_len >= 7000 else 5
                fact_check_markdown = fact_check_document_claims(
                    text=content,
                    summary_markdown=summary_markdown,
                    api_key=api_key,
                    base_url=base_url,
                    model=fact_model,
                    proxy_url=proxy_url,
                    max_claims=max_claims,
                )
            except Exception as fact_exc:
                print(f"Video fact check pipeline failed: {fact_exc}", flush=True)
                fact_check_markdown = _build_fact_check_fallback_markdown()

        normalized_payload["summary_markdown"] = summary_markdown
        normalized_payload["fact_check_markdown"] = fact_check_markdown if fact_check_enabled else ""
        return json.dumps(normalized_payload, ensure_ascii=False)

    except Exception as e:
        msg = str(e)
        if "Model does not exist" in msg or "code': 20012" in msg:
            msg += "\n\n提示：你使用的 Base URL 可能不支持该模型，请在下拉框选择正确的模型（如 deepseek-chat）或检查 API 文档。"
        elif "Incorrect API key" in msg or "code': 401" in msg:
             msg += "\n\n提示：API Key 错误，请检查是否填写正确。"
        return f"总结失败：{msg}"


def get_video_transcript(
    api: YouTubeTranscriptApi,
    video_id: str,
    video_url: str,
    languages: list[str] | None = None,
) -> str:
    asr_force_cpu = bool(getattr(api, "_asr_force_cpu", False))
    # 1. 检查是否为 Bilibili 视频
    # 如果是 Bilibili，直接使用 yt-dlp 或 whisper，跳过 YouTubeTranscriptApi
    if "bilibili.com" in video_url or re.match(r"^BV[a-zA-Z0-9]{10}$", video_id):
        video_url = normalize_video_url(video_url or video_id)
        proxy_url = str(getattr(api, "_effective_proxy", "") or "")
        timeout_seconds = float(getattr(api, "_timeout_seconds", 60.0) or 60.0)
        retries = int(getattr(api, "_retries", 2) or 2)
        status_cb = getattr(api, "_status_callback", None)
        local_fetch_node_mode = bool(str(os.environ.get("LOCAL_FETCH_NODE_MODE", "") or "").strip())
        remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()
        remote_worker_enabled = str(
            os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"
        ).strip().lower() in {"1", "true", "yes"}
        prefer_remote_first = remote_worker_enabled and remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}
        remote_worker_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
        remote_worker_summary = "disabled"
        running_on_render = bool(str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip())
        disable_render_asr_fallback = running_on_render and str(
            os.environ.get("REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK", "0") or "0"
        ).strip().lower() not in {"0", "false", "no"}
        cookies_from_browser = str(getattr(api, "_cookies_from_browser", "") or "")
        cookie_resolve_error = ""
        try:
            cookies_file = resolve_cookie_file(
                cookies_file=str(getattr(api, "_cookies_file", "") or ""),
                cookies_content=str(getattr(api, "_cookies_content", "") or ""),
                cookies_content_b64=str(getattr(api, "_cookies_content_b64", "") or ""),
            )
        except Exception as e:
            cookie_resolve_error = f"{type(e).__name__}:{e}"
            cookies_file = ""
        cookie_debug_summary = build_cookie_runtime_diagnostics(
            api,
            cookies_file=str(getattr(api, "_cookies_file", "") or ""),
            cookies_from_browser=cookies_from_browser,
            resolved_cookie_file=cookies_file,
            resolve_error=cookie_resolve_error,
        )
        disable_audio_transcribe = str(
            os.environ.get("DISABLE_AUDIO_TRANSCRIBE", "1") or "1"
        ).strip().lower() not in {"0", "false", "no"}
        asr_enabled = bool(getattr(api, "_asr_enabled", False)) and not disable_audio_transcribe
        asr_model = str(getattr(api, "_asr_model", "") or "")
        asr_language = str(getattr(api, "_asr_language", "") or "")
        asr_fast_mode = bool(getattr(api, "_asr_fast_mode", False))
        langs = expand_languages(languages or ["zh-Hans", "zh", "en"]) # B站默认中文优先

        if prefer_remote_first and remote_worker_url and not local_fetch_node_mode:
            try:
                if callable(status_cb):
                    status_cb("优先调用本地抓取节点处理 Bilibili 视频")
                remote_text = try_fetch_transcript_via_remote_worker(
                    video_id=video_id,
                    video_url=video_url,
                    languages=langs,
                    api=api,
                )
                if remote_text and not is_html_like_text(remote_text):
                    return remote_text
            except Exception as remote_exc:
                remote_worker_summary = f"{type(remote_exc).__name__}: {remote_exc}"
                if callable(status_cb):
                    status_cb(f"本地抓取节点处理 Bilibili 失败，回退 Render：{type(remote_exc).__name__}")

        # 尝试 yt-dlp 获取字幕 (B站可能有 CC 字幕)
        try:
            label, text = fetch_subtitles_with_ytdlp(
                video_url,
                preferred_langs=langs,
                proxy_url=proxy_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
            )
            if text and text.strip() and not is_html_like_text(text):
                header = f"[bilibili-cc | {label}]"
                return header + "\n\n" + text
        except Exception:
            pass
        
        # 尝试 Whisper 转写 (B站最常用)
        if asr_enabled:
            if prefer_remote_first and remote_worker_url and not local_fetch_node_mode and disable_render_asr_fallback:
                raise RuntimeError(
                    "Bilibili 视频未拿到字幕，且 Render 已启用低内存保护：已禁止在 Render 本机执行音频下载与 Whisper 转写。"
                    " 请确认本地抓取节点在线，并让任务优先在本地节点完成；如确实需要允许 Render 兜底，可将 "
                    "`REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK=0`。"
                    f"\n远程抓取诊断: {remote_worker_summary}"
                )
            try:
                status_cb = getattr(api, "_status_callback", None)
                label, text = transcribe_video_audio_with_ytdlp(
                    video_url=video_url,
                    proxy_url=proxy_url,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_from_browser,
                    model_name=asr_model,
                    language=asr_language,
                    status_callback=status_cb,
                    fast_mode=asr_fast_mode,
                    cookie_debug_summary=cookie_debug_summary,
                )
                return f"[bilibili-whisper | {label}]\n\n{text}"
            except Exception as e:
                raise RuntimeError(f"Bilibili 视频转写失败: {e}\nCookies 运行时诊断: {cookie_debug_summary}")
        
        raise RuntimeError("Bilibili 视频未找到可用字幕，且当前已禁用音频转写兜底。")

    # 2. YouTube 逻辑保持不变
    langs = expand_languages(languages or ["en"])
    disable_audio_transcribe = str(
        os.environ.get("DISABLE_AUDIO_TRANSCRIBE", "1") or "1"
    ).strip().lower() not in {"0", "false", "no"}
    asr_enabled = bool(getattr(api, "_asr_enabled", False)) and not disable_audio_transcribe
    asr_model = str(getattr(api, "_asr_model", "") or "")
    asr_language = str(getattr(api, "_asr_language", "") or "")
    asr_fast_mode = bool(getattr(api, "_asr_fast_mode", False))
    status_cb = getattr(api, "_status_callback", None)
    local_fetch_node_mode = bool(str(os.environ.get("LOCAL_FETCH_NODE_MODE", "") or "").strip())
    running_on_render = bool(str(os.environ.get("RENDER_SERVICE_ID", "") or "").strip())
    disable_render_asr_fallback = running_on_render and str(
        os.environ.get("REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK", "0") or "0"
    ).strip().lower() not in {"0", "false", "no"}
    local_skip_transcript_api = (
        local_fetch_node_mode
        and str(os.environ.get("LOCAL_FETCH_SKIP_TRANSCRIPT_API", "1") or "1").strip().lower() not in {"0", "false", "no"}
    )
    remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()
    remote_worker_enabled = str(
        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"
    ).strip().lower() in {"1", "true", "yes"}
    prefer_remote_first = remote_worker_enabled and remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}
    remote_worker_summary = "disabled"
    try:
        if prefer_remote_first and not str(os.environ.get("LOCAL_FETCH_NODE_MODE", "") or "").strip():
            remote_worker_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
            if remote_worker_url:
                try:
                    if callable(status_cb):
                        status_cb("优先调用本地抓取节点")
                    remote_text = try_fetch_transcript_via_remote_worker(
                        video_id=video_id,
                        video_url=video_url,
                        languages=langs,
                        api=api,
                    )
                    if remote_text and not is_html_like_text(remote_text):
                        return remote_text
                except Exception as remote_exc:
                    remote_worker_summary = f"{type(remote_exc).__name__}: {remote_exc}"
                    if callable(status_cb):
                        status_cb(f"本地抓取节点失败，回退 Render 直抓: {type(remote_exc).__name__}")
            else:
                remote_worker_summary = "not-configured"
        if local_skip_transcript_api:
            if callable(status_cb):
                status_cb(f"本地节点跳过 Transcript API，直接尝试 yt-dlp/Whisper: {video_id}")
            raise RequestBlocked("本地节点跳过 Transcript API")
        if callable(status_cb):
            status_cb(f"尝试 YouTube Transcript API: {video_id}")
        transcript = api.fetch(video_id, languages=langs)
        content = "\n".join([entry.text for entry in transcript])
        if is_html_like_text(content):
            raise RequestBlocked("返回 HTML 页面源码")
        header = f"[{transcript.language_code} | {'自动' if transcript.is_generated else '人工'}] 片段数: {len(transcript)}"
        return header + "\n\n" + content
    except NoTranscriptFound:
        if callable(status_cb):
            status_cb(f"Transcript API 未命中，尝试列出可用字幕: {video_id}")
        transcript_list = api.list(video_id)
        chosen = None
        for t in transcript_list:
            chosen = t
            if not t.is_generated:
                break
        if chosen is None:
            raise
        transcript = chosen.fetch()
        content = "\n".join([entry.text for entry in transcript])
        if is_html_like_text(content):
            raise RequestBlocked("返回 HTML 页面源码")
        header = f"[{transcript.language_code} | {'自动' if transcript.is_generated else '人工'}] 片段数: {len(transcript)}（已忽略语言优先级：{','.join(langs)}）"
        return header + "\n\n" + content
    except (TranscriptsDisabled, PoTokenRequired, RequestBlocked, IpBlocked, requests.exceptions.RequestException) as e:
        proxy_url = str(getattr(api, "_effective_proxy", "") or "")
        timeout_seconds = float(getattr(api, "_timeout_seconds", 60.0) or 60.0)
        retries = int(getattr(api, "_retries", 2) or 2)
        cookies_from_browser = str(getattr(api, "_cookies_from_browser", "") or "")
        cookie_resolve_error = ""
        try:
            cookies_file = resolve_cookie_file(
                cookies_file=str(getattr(api, "_cookies_file", "") or ""),
                cookies_content=str(getattr(api, "_cookies_content", "") or ""),
                cookies_content_b64=str(getattr(api, "_cookies_content_b64", "") or ""),
            )
        except Exception as resolve_exc:
            cookie_resolve_error = f"{type(resolve_exc).__name__}:{resolve_exc}"
            cookies_file = ""
        cookie_debug_summary = build_cookie_runtime_diagnostics(
            api,
            cookies_file=str(getattr(api, "_cookies_file", "") or ""),
            cookies_from_browser=cookies_from_browser,
            resolved_cookie_file=cookies_file,
            resolve_error=cookie_resolve_error,
        )
        if not prefer_remote_first and not str(os.environ.get("LOCAL_FETCH_NODE_MODE", "") or "").strip():
            remote_worker_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
            if remote_worker_url:
                try:
                    remote_text = try_fetch_transcript_via_remote_worker(
                        video_id=video_id,
                        video_url=video_url,
                        languages=langs,
                        api=api,
                    )
                    if remote_text and not is_html_like_text(remote_text):
                        return remote_text
                except Exception as remote_exc:
                    remote_worker_summary = f"{type(remote_exc).__name__}: {remote_exc}"
            else:
                remote_worker_summary = "not-configured"
        cookie_debug_summary = cookie_debug_summary + f"\n远程抓取诊断: {remote_worker_summary}"
        try:
            if callable(status_cb):
                status_cb(f"尝试 yt-dlp 字幕抓取: {video_id}")
            label, text = fetch_subtitles_with_ytdlp(
                video_url,
                preferred_langs=langs,
                proxy_url=proxy_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
            )
            if text and text.strip() and not is_html_like_text(text):
                header = f"[yt-dlp | {label}]"
                return header + "\n\n" + text
        except Exception:
            pass

        if asr_enabled:
            if prefer_remote_first and remote_worker_url and not local_fetch_node_mode and disable_render_asr_fallback:
                raise RuntimeError(
                    "未获取到可用字幕，且 Render 已启用低内存保护：已禁止在 Render 本机执行音频下载与 Whisper 转写。"
                    " 请确认本地抓取节点在线并优先处理该任务；如确实需要允许 Render 兜底，可将 "
                    "`REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK=0`。"
                    f"\n远程抓取诊断: {remote_worker_summary}"
                )
            if callable(status_cb):
                status_cb(f"尝试音频下载与 Whisper 转写: {video_id}")
            # 传递强制CPU标志到内部函数
            setattr(transcribe_video_audio_with_ytdlp, "_force_cpu", asr_force_cpu)
            label, text = transcribe_video_audio_with_ytdlp(
                video_url=video_url,
                proxy_url=proxy_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                model_name=asr_model,
                language=asr_language,
                status_callback=status_cb,
                fast_mode=asr_fast_mode,
                cookie_debug_summary=cookie_debug_summary,
            )
            return f"[asr | {label}]\n\n{text}"

        if cookie_debug_summary:
            raise RuntimeError(f"{e}\nCookies 运行时诊断: {cookie_debug_summary}")
        raise e


def list_available_transcripts(api: YouTubeTranscriptApi, video_id: str) -> str:
    transcript_list = api.list(video_id)
    rows = []
    for t in transcript_list:
        kind = "自动" if t.is_generated else "人工"
        translatable = "可翻译" if t.is_translatable else "不可翻译"
        rows.append(f"{t.language_code}\t{kind}\t{translatable}\t{t.language}")
    if not rows:
        return "未检测到任何字幕轨道。"
    return "language_code\t类型\t翻译\t语言\n" + "\n".join(rows)


def format_error(e: Exception) -> str:
    raw_msg = strip_ansi(str(e))
    if isinstance(e, (InvalidVideoId, ValueError)):
        msg = "无法解析视频 ID，请检查链接或直接粘贴 11 位 ID。"
    elif isinstance(e, TranscriptsDisabled):
        msg = "该视频字幕被关闭或不可用。可换一个有字幕的视频，或后续接入“音频转写兜底”。"
    elif isinstance(e, NoTranscriptFound):
        msg = "没有匹配你设置语言优先级的字幕。可先点“检测字幕”查看可用语言代码。"
    elif isinstance(e, (VideoUnavailable, VideoUnplayable)):
        msg = "视频不可用/不可播放（可能地区限制、删除或需要登录）。"
    elif isinstance(e, AgeRestricted):
        msg = "年龄限制视频，可能需要登录或不同的抓取方式。"
    elif isinstance(e, (IpBlocked, RequestBlocked)):
        msg = "请求被 YouTube 限制/风控。建议更换网络、降低频率或配置代理。"
    elif isinstance(e, PoTokenRequired):
        msg = "YouTube 需要 PoToken，当前方式可能抓不到字幕。"
    elif isinstance(e, requests.exceptions.ProxyError):
        msg = "代理不可用，请检查代理地址格式与连通性。"
    elif isinstance(e, requests.exceptions.ConnectTimeout):
        msg = "连接超时，请增大超时或使用代理/可访问网络。"
    elif isinstance(e, requests.exceptions.ChunkedEncodingError):
        msg = "连接中途断流（常见于代理/链路不稳定）。建议增大超时、提高重试次数，或更换更稳定的代理。"
    elif isinstance(e, requests.exceptions.ConnectionError):
        msg = "网络连接失败（可能无法访问 YouTube）。可尝试代理或更换网络。"
    elif isinstance(e, RuntimeError) and "yt-dlp" in str(e):
        msg = str(e)
    elif isinstance(e, RuntimeError) and "openai-whisper" in str(e):
        msg = str(e)
    elif isinstance(e, RuntimeError) and "音频转写失败" in str(e):
        msg = str(e)
    elif isinstance(e, KeyError) and "Linear" in raw_msg:
        msg = "Whisper 模型加载失败 (KeyError: Linear)。可能是 PyTorch 版本不兼容或模型文件损坏。建议尝试删除缓存的模型文件或重装 openai-whisper。"
    elif isinstance(e, FileNotFoundError) and ("ffmpeg" in raw_msg.lower() or "winerror 2" in raw_msg.lower()):
        msg = "未安装 ffmpeg（或未加入 PATH），无法进行音频转写。请先安装 ffmpeg 后重试。"
    elif ("could not copy" in raw_msg.lower() and "cookie" in raw_msg.lower()) or ("cookie database" in raw_msg.lower()) or ("could not find" in raw_msg.lower() and "cookies" in raw_msg.lower()):
        msg = "无法读取浏览器 Cookies（数据库被占用/无权限，或未找到对应浏览器的 Cookie 数据库）。建议关闭浏览器后重试，或切换可用浏览器/关闭自动读取 Cookies。"
    elif "HTTP Error 429" in raw_msg or "too many 429" in raw_msg.lower() or "429" in raw_msg:
        msg = "触发 YouTube 429 限流/风控。建议降低频率并等待一段时间，或使用更稳定的代理；也可启用“自动读取浏览器 Cookies”。"
    else:
        msg = str(e) or e.__class__.__name__

    msg = strip_ansi(msg)
    return f"失败原因：{msg}\n\n异常类型：{e.__class__.__name__}\n\n原始错误：{strip_ansi(repr(e))}"


def get_transcript_from_input(url_or_id: str, languages_csv: str) -> tuple[str, str, str]:
    video_url = normalize_video_url(url_or_id)
    video_id = extract_video_id(video_url)
    languages = [s.strip() for s in (languages_csv or "").split(",") if s.strip()]
    return video_id, video_url, ",".join(languages or ["zh-Hans", "zh", "en"])





def search_channels(
    keyword: str,
    limit: int = 3,
    proxy_url: str = "",
    timeout_seconds: float = 10.0
) -> dict:
    """
    搜索 YouTube 和 Bilibili 频道
    返回:
    {
        "youtube": [
            {"id": "...", "name": "...", "url": "...", "avatar": "...", "desc": "...", "platform": "youtube"},
            ...
        ],
        "bilibili": [
            {"id": "...", "name": "...", "url": "...", "avatar": "...", "desc": "...", "platform": "bilibili"},
            ...
        ]
    }
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor
    
    results = {"youtube": [], "bilibili": []}
    
    def _search_bilibili():
        try:
            # Bilibili User Search API
            api_url = "https://api.bilibili.com/x/web-interface/search/type"
            params = {
                "search_type": "bili_user",
                "keyword": keyword,
            }
            # Encode keyword for referer
            import urllib.parse
            encoded_kw = urllib.parse.quote(keyword)
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://search.bilibili.com/upuser?keyword={encoded_kw}",
                "Cookie": "buvid3=infoc;" # 简单的伪造 cookie 可能有助于绕过 412
            }
            
            # 使用 Session
            s = requests.Session()
            resp = s.get(api_url, params=params, headers=headers, timeout=timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("code") == 0:
                items = data.get("data", {}).get("result")
                if not items: return
                
                for item in items[:limit]:
                    # Bilibili user item: mid, uname, upic, usign
                    mid = str(item.get("mid"))
                    avatar = item.get("upic", "")
                    if avatar.startswith("//"):
                        avatar = "https:" + avatar
                        
                    results["bilibili"].append({
                        "id": mid,
                        "name": item.get("uname"),
                        "url": f"https://space.bilibili.com/{mid}",
                        "avatar": avatar,
                        "desc": item.get("usign", "")[:50] + "..." if item.get("usign") else "",
                        "platform": "bilibili"
                    })
        except Exception as e:
            print(f"Bilibili search failed: {e}")
            pass

    def _search_youtube():
        try:
            # YouTube Search via yt-dlp
            from yt_dlp import YoutubeDL
            
            opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "nocheckcertificate": True,
                "ignoreerrors": True,
                "socket_timeout": timeout_seconds,
            }
            if proxy_url:
                opts["proxy"] = proxy_url
            
            # 搜索稍微多一点，以便去重
            search_query = f"ytsearch{limit*2}:{keyword}"
            
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info: return
                
                entries = info.get("entries", [])
                seen_channels = set()
                
                for e in entries:
                    if not e: continue
                    c_id = e.get("channel_id") or e.get("uploader_id")
                    if not c_id: continue
                    
                    if c_id in seen_channels: continue
                    seen_channels.add(c_id)
                    
                    c_name = e.get("channel") or e.get("uploader")
                    c_url = e.get("channel_url") or f"https://www.youtube.com/channel/{c_id}"
                    
                    # 尝试获取头像 (fix: flat 模式无头像，需单独获取)
                    avatar_url = ""
                    try:
                        # 复用 get_channel_info 获取头像
                        # 注意：这会增加耗时，但为了头像显示是必要的
                        _, _, _, avatar_url = get_channel_info(
                           c_url, proxy_url, timeout_seconds=5.0
                        )
                    except:
                        pass
                    
                    results["youtube"].append({
                        "id": c_id,
                        "name": c_name,
                        "url": c_url,
                        "avatar": avatar_url,
                        "desc": "",
                        "platform": "youtube"
                    })
                    
                    if len(results["youtube"]) >= limit:
                        break
                        
        except Exception as e:
            # print(f"YouTube search failed: {e}")
            pass

    # 并发执行
    with ThreadPoolExecutor(max_workers=2) as executor:
        executor.submit(_search_bilibili)
        executor.submit(_search_youtube)
        
    return results


def get_channel_info(
    channel_url: str,
    proxy_url: str,
    timeout_seconds: float = 20.0,
    retries: int = 2,
    cookies_file: str = "",
    cookies_from_browser: str = "",
) -> tuple[str, str, str, str]:
    """
    获取频道信息
    返回: (channel_id, channel_name, canonical_url, avatar_url)
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise RuntimeError("未安装 yt-dlp")

    last_err: Exception | None = None
    
    # 尝试标准化 URL
    original_input = channel_url.strip()
    url_candidates = []

    if original_input.startswith("http"):
        url_candidates.append(original_input)
    elif original_input.startswith("@"):
        url_candidates.append(f"https://www.youtube.com/{original_input}")
    elif re.match(r"^BV[a-zA-Z0-9]{10}$", original_input):
        # Bilibili BV ID
        pass
    elif re.match(r"^\d+$", original_input):
        # 纯数字可能是 Bilibili UID
        url_candidates.append(f"https://space.bilibili.com/{original_input}")
    else:
        # 1. 假设是 channel ID
        if re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", original_input):
            url_candidates.append(f"https://www.youtube.com/channel/{original_input}")
        # 2. 尝试 ytsearch
        url_candidates.append(f"ytsearch1:{original_input}")

    # Bilibili API fallback
    # 如果 URL 是 B站空间链接，直接解析 mid 并调用 API
    # 避免 yt-dlp 412 错误
    bili_mid = None
    if "bilibili.com" in original_input:
        import re
        # 匹配 space.bilibili.com/123456
        m = re.search(r"space\.bilibili\.com/(\d+)", original_input)
        if m:
            bili_mid = m.group(1)
        
    if bili_mid:
        try:
            import requests
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://space.bilibili.com/{bili_mid}",
            }
            api_url = f"https://api.bilibili.com/x/space/acc/info?mid={bili_mid}"
            resp = requests.get(api_url, headers=headers, timeout=timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    info_data = data.get("data", {})
                    c_id = str(info_data.get("mid"))
                    c_name = info_data.get("name")
                    c_avatar = info_data.get("face", "")
                    if c_avatar.startswith("//"):
                        c_avatar = "https:" + c_avatar
                    # 强制 B站图片使用 https
                    if "hdslb.com" in c_avatar and c_avatar.startswith("http://"):
                        c_avatar = c_avatar.replace("http://", "https://")
                        
                    c_url = f"https://space.bilibili.com/{c_id}"
                    
                    return str(c_id), str(c_name), str(c_url), str(c_avatar), "bilibili"
        except Exception:
            pass # Fallback to yt-dlp if API fails
    
    # 强制 B站 API 请求带上 Cookie
    # 如果上面简单的 requests 失败了 (可能因为没有 cookie)，
    # 这里我们不需要做什么，因为下面会进入 yt-dlp 流程。
    # 但 yt-dlp 也会失败 (412)。
    # 所以我们需要确保上面的 API 请求能成功。
    if bili_mid:
         try:
             import requests
             # 使用 Session 并伪造更完整的 Header
             s = requests.Session()
             headers = {
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                 "Referer": f"https://space.bilibili.com/{bili_mid}",
                 "Cookie": "buvid3=infoc;" # 尝试添加 cookie
             }
             api_url = f"https://api.bilibili.com/x/space/acc/info?mid={bili_mid}"
             resp = s.get(api_url, headers=headers, timeout=timeout_seconds)
             if resp.status_code == 200:
                 data = resp.json()
                 if data.get("code") == 0:
                     info_data = data.get("data", {})
                     c_id = str(info_data.get("mid"))
                     c_name = info_data.get("name")
                     c_avatar = info_data.get("face", "")
                     if c_avatar.startswith("//"):
                         c_avatar = "https:" + c_avatar
                     c_url = f"https://space.bilibili.com/{c_id}"
                     return str(c_id), str(c_name), str(c_url), str(c_avatar), "bilibili"
         except Exception:
             pass

    for attempt in range(max(1, int(retries))):
        for candidate_url in url_candidates:
            for cookiefile, cfb in CookieManager.get_sources(cookies_file, cookies_from_browser, False):
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": True,
                    "playlistend": 1, # 我们只需要频道元数据
                    "socket_timeout": float(timeout_seconds),
                    "nocheckcertificate": True,
                    "ignoreerrors": True, # 忽略错误，以便尝试下一个候选
                }
                if proxy_url:
                    opts["proxy"] = proxy_url
                if cookiefile:
                    opts["cookiefile"] = cookiefile
                elif cfb:
                    opts["cookiesfrombrowser"] = (cfb,)

                with YoutubeDL(opts) as ydl:
                    try:
                        info = ydl.extract_info(candidate_url, download=False)
                        if not info:
                            continue
                        
                        # 如果是搜索结果，info['entries'] 会包含视频列表
                        if "entries" in info:
                            entries = info.get("entries", [])
                            if not entries:
                                continue
                            # 取第一个视频的信息
                            info = entries[0]
                        
                        # 尝试提取信息
                        c_id = info.get("channel_id") or info.get("uploader_id")
                        c_name = info.get("channel") or info.get("uploader") or info.get("title")
                        c_url = info.get("channel_url") or info.get("uploader_url")
                        
                        # 尝试提取头像
                        c_avatar = ""

                        # 确定平台
                        platform = "youtube"
                        if "bilibili.com" in candidate_url or "space.bilibili.com" in str(c_url):
                            platform = "bilibili"
                        
                        # 优先从 thumbnails 提取
                        thumbnails = info.get("thumbnails")
                        if thumbnails:
                            # 1. 尝试找 B站特有的 face 字段 (yt-dlp 可能会映射到 thumbnail 列表)
                            # 或者找 id 为 avatar_uncropped
                            for t in thumbnails:
                                if t.get("id") == "avatar_uncropped":
                                    c_avatar = t.get("url")
                                    break

                            # 2. 如果是 YouTube，优先找 ggpht.com 的图片 (这是频道头像)，避开 ytimg.com (这是视频封面)
                            if not c_avatar and platform == "youtube":
                                for t in thumbnails:
                                    u = t.get("url", "")
                                    if "ggpht.com" in u:
                                        c_avatar = u
                                        break
                            
                            # 3. 如果是 Bilibili，尝试从 entries[0] 获取 uploader_id 
                            # 然后构造 API 请求或从视频 info 中找头像 (yt-dlp 对 B站频道页解析的 thumbnails 往往是视频封面而非头像)
                            if not c_avatar and ("bilibili.com" in candidate_url or "space.bilibili.com" in str(c_url)):
                                # B站频道解析时，thumbnails 往往是视频封面，而不是头像
                                # 尝试从 entries 中获取第一个视频的 uploader 信息，有时候会有头像
                                if "entries" in info:
                                    entries = info.get("entries", [])
                                    if entries:
                                        first_entry = entries[0]
                                        # 尝试直接请求 API 获取头像 (需要 uploader_id)
                                        # 但这里为了简单，我们先看 first_entry 是否有 owner_thumbnail
                                        # yt-dlp 对 B站视频通常不返回 owner_thumbnail
                                        pass
                                
                                # B站兜底：如果实在找不到，尝试用 requests 请求 B站 API
                                # https://api.bilibili.com/x/space/acc/info?mid={mid}
                                # 需要 mid
                                if not c_avatar and c_id and c_id.isdigit():
                                    try:
                                        import requests
                                        # 简单的 API 请求，不带 cookie 可能会失败，但值得一试
                                        headers = {"User-Agent": "Mozilla/5.0"}
                                        r = requests.get(f"https://api.bilibili.com/x/space/acc/info?mid={c_id}", headers=headers, timeout=5)
                                        if r.status_code == 200:
                                            j = r.json()
                                            if j.get("code") == 0:
                                                c_avatar = j.get("data", {}).get("face", "")
                                    except:
                                        pass

                            # 4. 常规逻辑：找正方形图片
                            if not c_avatar:
                                for t in thumbnails:
                                    w = t.get("width")
                                    h = t.get("height")
                                    if w and h and w == h:
                                        # 再次检查：如果是 YouTube，排除 ytimg
                                        if platform == "youtube" and "ytimg.com" in t.get("url", ""):
                                            continue
                                        c_avatar = t.get("url")
                                        break
                            
                            # 5. 兜底：取最后一个 (通常是最大的)
                            if not c_avatar and len(thumbnails) > 0:
                                # 如果是 YouTube，尽量不要取 ytimg
                                candidate = thumbnails[-1].get("url")
                                if platform == "youtube" and "ytimg.com" in candidate:
                                    # 尝试往前找一个不是 ytimg 的
                                    for t in reversed(thumbnails):
                                        if "ytimg.com" not in t.get("url", ""):
                                            c_avatar = t.get("url")
                                            break
                                else:
                                    c_avatar = candidate

                        if c_id and c_name:
                            # 规范化 channel url (优先用 handle url 或 channel id url)
                            if not c_url:
                                if "youtube.com" in candidate_url:
                                    c_url = f"https://www.youtube.com/channel/{c_id}"
                                elif "bilibili.com" in candidate_url:
                                    c_url = f"https://space.bilibili.com/{c_id}"
                                else:
                                    c_url = candidate_url # Fallback
                            
                            return str(c_id), str(c_name), str(c_url), str(c_avatar or ""), platform
                            
                    except Exception as e:
                        last_err = e
                        continue
            
            # 如果当前 candidate 成功返回了，上面就 return 了
            # 如果失败了，继续下一个 candidate (例如先试 channel id 失败，再试搜索)
    
    if last_err:
        raise RuntimeError(strip_ansi(str(last_err)))
    raise RuntimeError(f"无法找到频道信息: {original_input}")




def get_channel_recent_videos(
    channel_url: str,
    limit: int = 5,
    proxy_url: str = "",
    timeout_seconds: float = 20.0,
    retries: int = 2,
    cookies_file: str = "",
    cookies_from_browser: str = "",
    filter_longest: bool = False,
    min_duration_seconds: int = 0,
    only_streams: bool = False,
) -> list[dict]:
    """
    获取频道最新视频，支持混合扫描 /videos 和 /streams 以确保不错过长直播回放。
    
    filter_longest: 如果为 True，将采用"混合提取"策略：
      1. 快速扫描 /videos 和 /streams 获取候选列表
      2. 对前 15 个候选视频进行详细抓取(获取准确时长和日期)
      3. 在最近发布的 6 个视频中选择时长最长的一个
    
    min_duration_seconds: 最小时长限制（秒），用于过滤短视频。
    
    only_streams: 如果为 True，仅扫描 /streams 页面（针对直播回放为主的频道）。
    
    返回: list of {id, title, url, upload_date, duration}
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        raise RuntimeError("未安装 yt-dlp")

    from datetime import datetime

    def _build_video_item(raw_item: dict, fallback_url: str = "") -> dict:
        """标准化视频元数据，便于统一排序与展示。"""
        timestamp = raw_item.get("timestamp") or raw_item.get("release_timestamp") or 0
        upload_date = raw_item.get("upload_date")
        if not upload_date and timestamp:
            try:
                upload_date = datetime.fromtimestamp(int(timestamp)).strftime("%Y%m%d")
            except Exception:
                upload_date = ""
        return {
            "id": raw_item.get("id"),
            "title": raw_item.get("title", "无标题"),
            "url": raw_item.get("url") or raw_item.get("webpage_url") or fallback_url,
            "upload_date": upload_date,
            "duration": raw_item.get("duration") or 0,
            "timestamp": int(timestamp) if timestamp else 0,
        }

    def _video_sort_key(item: dict) -> tuple[int, str, int]:
        """优先按精确时间排序，缺失时回退到 upload_date 和时长。"""
        upload_date = str(item.get("upload_date") or "")
        return (
            int(item.get("timestamp") or 0),
            upload_date,
            int(item.get("duration") or 0),
        )

    base_url = channel_url.strip().rstrip("/")
    # 构造待扫描的 tab 列表
    # 如果是 Bilibili，直接扫描主页 (yt-dlp 会自动处理)
    if "bilibili.com" in base_url:
        targets = [base_url]
    else:
        # YouTube 逻辑
        # 初始化 targets 列表
        targets = []
        
        if only_streams:
            # 强制仅扫描直播回放页面
            targets.append(base_url + "/streams")
        # 如果明确指定了 tab，就只扫那个；否则扫 videos 和 streams
        elif any(x in base_url for x in ["/videos", "/shorts", "/streams", "/live", "/featured"]):
            targets.append(base_url)
        else:
            targets.append(base_url + "/videos")
            targets.append(base_url + "/streams")

    candidates_map = {}  # id -> item

    for attempt in range(max(1, int(retries))):
        for cookiefile, cfb in CookieManager.get_sources(cookies_file, cookies_from_browser, False):
            # 第一步：快速扫描 (extract_flat=True)
            for target_url in targets:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": True,
                    "playlistend": 15,  # 扩大扫描范围到前 15 个，确保即便有一堆 Shorts 也能扫到正片
                    "socket_timeout": float(timeout_seconds),
                    "nocheckcertificate": True,
                    "ignoreerrors": True,
                }
                if proxy_url:
                    opts["proxy"] = proxy_url
                if cookiefile:
                    opts["cookiefile"] = cookiefile
                elif cfb:
                    opts["cookiesfrombrowser"] = (cfb,)

                with YoutubeDL(opts) as ydl:
                    try:
                        info = ydl.extract_info(target_url, download=False)
                        if not info:
                            continue
                        
                        entries = info.get("entries", [])
                        for e in entries:
                            if not e: continue
                            v_id = e.get("id")
                            if not v_id: continue
                            
                            # 记录基础信息
                            if v_id not in candidates_map:
                                candidates_map[v_id] = _build_video_item(
                                    e,
                                    fallback_url=f"https://www.youtube.com/watch?v={v_id}",
                                )
                    except Exception:
                        pass
            
            if candidates_map:
                break
        if candidates_map:
            break

    if not candidates_map:
        return []

    # 转为列表
    all_candidates = list(candidates_map.values())

    # 如果不需要过滤长视频，仍然必须先按发布时间排序，不能依赖抓取顺序。
    if not filter_longest:
        all_candidates.sort(key=_video_sort_key, reverse=True)
        return all_candidates[: max(1, int(limit or 1))]

    # === filter_longest 混合模式逻辑 ===
    # 优化：如果 all_candidates 中已经有 duration 和 upload_date，则不需要 fetch_detail
    # 只有当 duration 为 0/None 或者需要精确过滤时才 fetch_detail
    
    # 预过滤：如果 flat 模式已经拿到了时长，且明显小于阈值，直接排除
    # 这样可以避免对 Shorts 发起无意义的 detail 请求，大幅提升速度
    threshold_duration = min_duration_seconds if min_duration_seconds > 0 else 180
    
    check_list = []
    for item in all_candidates:
        flat_dur = item.get("duration")
        # 如果时长已知且小于阈值，直接跳过 (Shorts 过滤)
        if flat_dur and flat_dur > 0 and flat_dur < threshold_duration:
            continue
        check_list.append(item)

    detailed_results = []
    
    # 需要 fetch 的列表
    need_fetch = []
    # 已经可以直接用的列表
    ready_results = []
    
    for item in check_list:
        # 如果是 YouTube，flat 模式通常有 duration
        # 但 upload_date 有时是 None 或者 'NA'
        # 如果 duration > 0 且有 upload_date，直接用
        
        has_dur = item.get("duration") and item.get("duration") > 0
        has_date = item.get("upload_date")
        
        # 如果有了 duration 和 date，直接复用，不重新抓取
        if has_dur and has_date:
            ready_results.append(item)
        else:
            need_fetch.append(item)
            
    # 如果所有都需要 fetch，或者需要更精确的信息
    # 为了保险起见，如果 need_fetch 很多，我们只取前 10 个去 fetch
    if need_fetch:
        need_fetch = need_fetch[:10]

    def fetch_detail_item(item, proxy_url_val):
        try:
            # 缩短单个视频的超时时间，因为如果太慢通常是网络问题
            local_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "socket_timeout": 5, # 再次缩短超时到 5s
                "nocheckcertificate": True,
                "ignoreerrors": True,
            }
            if proxy_url_val:
                local_opts["proxy"] = proxy_url_val
                
            with YoutubeDL(local_opts) as ydl:
                info = ydl.extract_info(item["url"], download=False)
                if info:
                    return _build_video_item(info, fallback_url=item["url"])
        except Exception:
            pass
        # 失败则返回原始数据
        return item

    if need_fetch:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 限制并发数，避免瞬间太多请求
        # 提高内部并发数到 10，加快单个频道的处理速度
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_detail_item, item, proxy_url) for item in need_fetch]
            for future in as_completed(futures):
                res = future.result()
                detailed_results.append(res)
    
    # 合并结果
    detailed_results.extend(ready_results)
            
    # 过滤掉获取不到日期的（极少情况）
    valid_results = [x for x in detailed_results if x.get("upload_date") or x.get("timestamp")]

    # 基础时长过滤：默认 180s (3分钟)，如果指定了 min_duration_seconds 则使用指定值
    # 这一步更严格地排除掉 Shorts/剪辑片段/预告片等干扰项，只保留正片
    threshold_duration = min_duration_seconds if min_duration_seconds > 0 else 180
    valid_results = [x for x in valid_results if x.get("duration", 0) >= threshold_duration]

    # 按日期降序排序 (最新的在前)
    # 注意：yt-dlp 返回的日期格式是 YYYYMMDD，字符串比较即可
    valid_results.sort(key=_video_sort_key, reverse=True)

    if not valid_results:
        # 如果过滤完没视频了，尝试放宽标准找一个最长的，避免完全空
        # 比如有些正片可能只有 2 分钟，或者全是短片时至少给一个
        detailed_results.sort(
            key=lambda x: (_video_sort_key(x), int(x.get("duration") or 0)),
            reverse=True,
        )
        if detailed_results:
             return [detailed_results[0]]
        return []

    # 获取今天的日期字符串
    from datetime import datetime
    today_str = datetime.now().strftime("%Y%m%d")

    # 逻辑回退到"简单而健壮"的版本，但增加 scan 深度。
    # 用户反馈之前的版本更好，说明复杂的"今天/昨天"逻辑可能有误判（特别是跨时区时）。
    # 最朴素的需求：
    # 1. 必须是"最近"发布的。
    # 2. 尽量是"正片"（长视频）。
    
    # 我们已经有了 valid_results，它是按 upload_date 降序排列的。
    # 并且已经过滤掉了 < 3分钟的短片。
    
    # 直接取前 3 个。
    # 为什么这样是对的？
    # 1. 如果今天发了 3 个视频，都是长视频 -> 取前3个 -> 正确。
    # 2. 如果今天发了 1 个长视频，昨天发了 2 个 -> 取前3个 -> 正确（包含了最新的）。
    # 3. 如果今天没发，昨天发了 1 个 -> 取前3个 -> 正确（包含了最新的）。
    
    # 唯一的问题：如果今天发了 5 个视频，前 3 个是短评(5min)，第 4 个是正片(30min)。
    # 按时间排序会取前 3 个短评，漏掉正片。
    # 但用户同时也抱怨"不是最新时间的"。
    # 这说明"时间"的优先级 > "时长"。
    # 如果为了找长视频而去取旧视频，用户会不满意。
    
    # 折中方案：
    # 在最近的 N 个（比如 5 个）候选视频中，优先展示。
    # 如果我们直接返回前 3 个，这是最符合"Timeline"逻辑的。
    # 用户说"还不如之前的"，之前的逻辑其实是"取最近10个 -> 加权打分 -> 取1个"。
    # 现在用户要"取3个"。
    
    # 让我们尝试最直观的逻辑：
    # 返回【最近发布的】且【时长合格】的视频，最多 3 个。
    # 不做任何额外的日期分组或时长重排序，完全信任时间轴。
    
    return valid_results[: max(1, int(limit or 1))]


def check_network(proxy_url: str, timeout: float = 5.0) -> str | None:
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        
        def _do_check(verify: bool) -> None:
            s = requests.Session()
            s.trust_env = False
            if proxies:
                s.proxies.update(proxies)
            # 先试 Google
            try:
                r = s.get("https://www.google.com", timeout=timeout, stream=True, verify=verify)
                r.close()
                return
            except Exception:
                pass
            # 再试 YouTube
            r = s.get("https://www.youtube.com", timeout=timeout, stream=True, verify=verify)
            r.close()

        try:
            _do_check(verify=True)
            return None
        except Exception as e1:
            # 如果第一次失败，尝试关闭 SSL 验证（针对某些中间人代理）
            try:
                _do_check(verify=False)
                return None
            except Exception:
                # 如果还是失败，返回第一次的错误
                return f"{e1.__class__.__name__}: {e1}"
    except Exception as e:
        return f"{e.__class__.__name__}: {e}"
