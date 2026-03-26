import re
import threading
import time
import os
import json
import tempfile
import shutil
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 自动配置 ffmpeg 环境
try:
    import imageio_ffmpeg
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    if ffmpeg_path:
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        # imageio-ffmpeg 的可执行文件可能带版本号（如 ffmpeg-win-x86_64-v7.1.exe）
        # whisper 默认调用 'ffmpeg'，所以必须确保目录下有 ffmpeg.exe
        target_ffmpeg = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(target_ffmpeg):
            print(f"正在创建 ffmpeg.exe 副本: {target_ffmpeg}")
            shutil.copy2(ffmpeg_path, target_ffmpeg)
        
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
            print(f"已自动添加 ffmpeg 到 PATH: {ffmpeg_dir}")
except ImportError:
    print("未安装 imageio-ffmpeg，无法自动配置 ffmpeg 环境。")
except Exception as e:
    print(f"自动配置 ffmpeg 环境失败: {e}")

import requests
import webbrowser
from youtube_transcript_api import YouTubeTranscriptApi
from requests.adapters import HTTPAdapter
from urllib3 import Retry
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

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

CONFIG_FILE = "config.json"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


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


def extract_video_id(url_or_id: str) -> str:
    candidate = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate) and (
        candidate.startswith("www.") or "youtube.com" in candidate or "youtu.be" in candidate
    ):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()

    if "youtu.be" in host:
        video_id = parsed.path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id

    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            video_id = qs["v"][0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id

        m = re.search(r"/(shorts|embed)/([A-Za-z0-9_-]{11})", parsed.path)
        if m:
            return m.group(2)

    raise ValueError("无法从输入解析出 video_id（支持 11 位 ID / youtu.be / youtube.com?v= / shorts / embed）")


def normalize_youtube_url(url_or_id: str) -> str:
    s = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return f"https://www.youtube.com/watch?v={s}"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s) and (
        s.startswith("www.") or "youtube.com" in s or "youtu.be" in s
    ):
        s = "https://" + s
    return s


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


def get_effective_proxy(proxy_url: str, use_system_proxy: bool) -> tuple[str, str]:
    proxy_url = (proxy_url or "").strip()
    if proxy_url:
        return proxy_url, ""
    if use_system_proxy:
        return detect_windows_proxy()
    return "", ""


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

    langs = preferred_langs[:] if preferred_langs else []
    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        last_err: Exception | None = None
        last_video_id = ""

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

        def is_cookie_error(msg: str) -> bool:
            s = strip_ansi(str(msg or "")).lower()
            return (
                "could not copy" in s
                and "cookie" in s
                and ("chrome" in s or "edge" in s or "chromium" in s or "brave" in s)
            ) or ("cookie database" in s) or ("database is locked" in s) or ("permission denied" in s)

        def cookie_sources() -> list[tuple[str, str]]:
            file_path = (cookies_file or "").strip()
            browser = (cookies_from_browser or "").strip()
            if file_path:
                return [(file_path, "")]
            if not browser:
                return [("", "")]
            if browser == "chrome":
                return [("", ""), ("", "chrome"), ("", "edge"), ("", "firefox")]
            if browser == "edge":
                return [("", ""), ("", "edge"), ("", "chrome"), ("", "firefox")]
            return [("", ""), ("", browser)]

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
            sess = build_download_session()
            client_sets: list[list[str]] = [["android", "web"], ["web"], ["ios", "web"]]
            attempt_retries = max(1, int(retries))
            for client_set in client_sets:
                for attempt in range(attempt_retries):
                    ua = random.choice(user_agents)
                    for cookiefile, cfb in cookie_sources():
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

                        with YoutubeDL(opts) as ydl:
                            try:
                                info = ydl.extract_info(video_url, download=False)
                            except DownloadError as e:
                                last_msg = strip_ansi(str(e))
                                last_err = e
                                if "HTTP Error 429" in last_msg or "429" in last_msg:
                                    time.sleep(2.5 * (attempt + 1))
                                    continue
                                if cfb and is_cookie_error(last_msg):
                                    continue
                                continue
                            except Exception as e:
                                last_err = e
                                if cfb and is_cookie_error(e):
                                    continue
                                continue
                        if info is not None:
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
            nonlocal last_err, last_video_id
            attempt_retries = max(1, int(retries))
            for attempt in range(attempt_retries):
                ua = random.choice(user_agents)
                for cookiefile, cfb in cookie_sources():
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
                        "http_headers": {"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
                        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
                        "logger": logger,
                    }
                    if proxy_url:
                        opts["proxy"] = proxy_url
                    if cookiefile:
                        opts["cookiefile"] = cookiefile
                    elif cfb:
                        opts["cookiesfrombrowser"] = (cfb,)

                    with YoutubeDL(opts) as ydl:
                        try:
                            info = ydl.extract_info(video_url, download=True)
                            last_video_id = (info or {}).get("id") or last_video_id
                            last_err = None
                            vtts = sorted(Path(tmp).glob("*.vtt"))
                            if vtts:
                                return last_video_id, vtts
                            last_err = RuntimeError("yt-dlp 未下载到字幕文件（可能无字幕或被限制）。")
                            break
                        except DownloadError as e:
                            last_err = RuntimeError(strip_ansi(str(e)) + "\n\n" + "\n".join(logger.lines[-80:]))
                            msg = strip_ansi(str(e))
                            if "HTTP Error 429" in msg or "429" in msg:
                                time.sleep(2.0 * (attempt + 1))
                                continue
                            if cfb and is_cookie_error(msg):
                                continue
                            continue
                        except Exception as e:
                            last_err = RuntimeError(repr(e) + "\n\n" + "\n".join(logger.lines[-80:]))
                            if cfb and is_cookie_error(e):
                                continue
                            continue
            return last_video_id, []

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

        if last_err is not None:
            raise last_err
        raise RuntimeError("yt-dlp 兜底抓取失败（未知原因）。")


def transcribe_audio_with_whisper(audio_path: str, model_name: str, language: str) -> str:
    try:
        import whisper  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "未安装 openai-whisper，无法启用音频转写兜底。可执行：python -m pip install openai-whisper -i https://pypi.tuna.tsinghua.edu.cn/simple"
        ) from e

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
    result = model.transcribe(audio_path, language=lang, fp16=False)
    text = str((result or {}).get("text") or "").strip()
    if not text:
        raise RuntimeError("音频转写结果为空。")
    return text


def transcribe_video_audio_with_ytdlp(
    video_url: str,
    proxy_url: str,
    timeout_seconds: float,
    retries: int,
    cookies_file: str,
    cookies_from_browser: str,
    model_name: str,
    language: str,
) -> tuple[str, str]:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
        from yt_dlp.utils import DownloadError  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "未安装 yt-dlp，无法启用音频转写兜底。可执行：python -m pip install yt-dlp -i https://pypi.tuna.tsinghua.edu.cn/simple"
        ) from e

    def cookie_sources() -> list[tuple[str, str]]:
        file_path = (cookies_file or "").strip()
        browser = (cookies_from_browser or "").strip()
        if file_path:
            return [(file_path, "")]
        if not browser:
            return [("", "")]
        if browser == "chrome":
            return [("", ""), ("", "chrome"), ("", "edge"), ("", "firefox")]
        if browser == "edge":
            return [("", ""), ("", "edge"), ("", "chrome"), ("", "firefox")]
        return [("", ""), ("", browser)]

    def is_cookie_error(msg: str) -> bool:
        s = strip_ansi(str(msg or "")).lower()
        return (
            "could not copy" in s
            and "cookie" in s
            and ("chrome" in s or "edge" in s or "chromium" in s or "brave" in s)
        ) or ("cookie database" in s) or ("database is locked" in s) or ("permission denied" in s)

    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        last_err: Exception | None = None
        last_video_id = ""
        for attempt in range(max(1, int(retries))):
            for cookiefile, cfb in cookie_sources():
                opts: dict = {
                    "format": "bestaudio/best",
                    "outtmpl": outtmpl,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "verbose": True,
                    "nocheckcertificate": True,
                    "socket_timeout": float(timeout_seconds),
                    "retries": 1,
                }
                if proxy_url:
                    opts["proxy"] = proxy_url
                if cookiefile:
                    opts["cookiefile"] = cookiefile
                elif cfb:
                    opts["cookiesfrombrowser"] = (cfb,)

                with YoutubeDL(opts) as ydl:
                    try:
                        info = ydl.extract_info(video_url, download=True)
                        if isinstance(info, dict):
                            last_video_id = str(info.get("id") or last_video_id)
                    except DownloadError as e:
                        msg = strip_ansi(str(e))
                        last_err = e
                        if "HTTP Error 429" in msg or "429" in msg:
                            time.sleep(2.0 * (attempt + 1))
                            continue
                        if cfb and is_cookie_error(msg):
                            continue
                        continue
                    except Exception as e:
                        last_err = e
                        if cfb and is_cookie_error(str(e)):
                            continue
                        continue

                candidates = []
                for p in Path(tmp).glob("*"):
                    if not p.is_file():
                        continue
                    ext = p.suffix.lower()
                    if ext in {".m4a", ".webm", ".mp3", ".wav", ".opus", ".aac", ".flac", ".ogg"}:
                        candidates.append(p)
                if not candidates:
                    last_err = RuntimeError("未下载到音频文件（可能被限制或链接无效）。")
                    continue
                audio = max(candidates, key=lambda x: x.stat().st_size)
                text = transcribe_audio_with_whisper(str(audio), model_name=model_name, language=language)
                label = f"{last_video_id or audio.stem} | whisper:{(model_name or '').strip() or 'base'}"
                return label, text

        if last_err is not None:
            raise last_err
        raise RuntimeError("音频转写兜底失败（未知原因）。")


def fetch_available_models(api_key: str, base_url: str, proxy_url: str = None) -> list[str]:
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
        
        # 兼容不同返回格式，提取 id
        model_ids = []
        for m in models_page:
            if hasattr(m, "id"):
                model_ids.append(m.id)
            elif isinstance(m, dict):
                model_ids.append(m.get("id"))
                
        return sorted(model_ids)
    except Exception as e:
        raise RuntimeError(f"获取模型列表失败: {e}")

def summarize_text(text: str, api_key: str, base_url: str, model: str, proxy_url: str = None) -> str:
    if not text or not text.strip():
        return "没有可总结的内容（文本为空）。"
    if not api_key:
        return "请填写 API Key 以启用总结功能。"
    
    try:
        from openai import OpenAI
        import httpx
    except ImportError:
        return "未安装 openai 库，无法进行总结。"

    try:
        # 构造客户端
        client_kwargs = {"api_key": api_key}
        if base_url and base_url.strip():
            client_kwargs["base_url"] = base_url.strip()
        
        # 配置 httpx client (代理 + 禁用 SSL 验证)
        httpx_kwargs = {"verify": False}
        if proxy_url and proxy_url.strip():
            httpx_kwargs["proxy"] = proxy_url.strip()
        
        client_kwargs["http_client"] = httpx.Client(**httpx_kwargs)
        
        client = OpenAI(**client_kwargs)
        
        # 简单截断防止超长 (假设大约 12k 字符内安全，具体视模型而定)
        # 实际生产中应使用 token 计算或分段总结
        content = text.strip()
        if len(content) > 20000:
            content = content[:20000] + "\n...(内容过长已截断)..."

        prompt = (
            "请对以下视频字幕内容进行详细总结。\n"
            "要求：\n"
            "1. 归纳视频的核心主题和背景。\n"
            "2. 提炼出 5-10 个关键要点（Key Points）。\n"
            "3. 总结视频的最终结论或核心观点。\n"
            "4. 输出格式清晰，使用 Markdown 列表。\n\n"
            "字幕内容：\n"
            f"{content}"
        )

        response = client.chat.completions.create(
            model=model.strip() or "gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一个专业的视频内容总结助手。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        
        # 增加鲁棒性处理：某些情况下可能返回 JSON 字符串或字典
        raw_resp = response
        if isinstance(raw_resp, str):
            if raw_resp.strip().lstrip().startswith("<"):
                # 检测到 HTML 响应
                return f"总结失败：返回了 HTML 内容而非 JSON。\n可能原因：\n1. Base URL 填写错误（填写了网页地址而非 API 地址）。\n2. 代理/网关拦截了请求并返回了错误页面。\n\n原始响应预览:\n{raw_resp[:500]}"
            
            try:
                raw_resp = json.loads(raw_resp)
            except Exception:
                pass
        
        summary = ""
        if isinstance(raw_resp, dict):
            # 字典访问模式
            choices = raw_resp.get("choices", [])
            if choices and len(choices) > 0:
                msg = choices[0].get("message", {})
                summary = msg.get("content", "")
        else:
            # 对象属性访问模式 (OpenAI v1 standard)
            if hasattr(raw_resp, "choices") and len(raw_resp.choices) > 0:
                summary = raw_resp.choices[0].message.content
        
        if not summary:
            # 如果没拿到，打印原始响应以便调试
            return f"总结失败：无法解析响应内容。\n原始响应类型: {type(response)}\n原始响应: {str(response)[:500]}"

        return f"【AI 总结结果】\n\n{summary}"

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
    langs = expand_languages(languages or ["en"])
    asr_enabled = bool(getattr(api, "_asr_enabled", False))
    asr_model = str(getattr(api, "_asr_model", "") or "")
    asr_language = str(getattr(api, "_asr_language", "") or "")
    try:
        transcript = api.fetch(video_id, languages=langs)
        header = f"[{transcript.language_code} | {'自动' if transcript.is_generated else '人工'}] 片段数: {len(transcript)}"
        return header + "\n\n" + "\n".join([entry.text for entry in transcript])
    except NoTranscriptFound:
        transcript_list = api.list(video_id)
        chosen = None
        for t in transcript_list:
            chosen = t
            if not t.is_generated:
                break
        if chosen is None:
            raise
        transcript = chosen.fetch()
        header = f"[{transcript.language_code} | {'自动' if transcript.is_generated else '人工'}] 片段数: {len(transcript)}（已忽略语言优先级：{','.join(langs)}）"
        return header + "\n\n" + "\n".join([entry.text for entry in transcript])
    except (TranscriptsDisabled, PoTokenRequired, RequestBlocked, IpBlocked, requests.exceptions.RequestException) as e:
        proxy_url = str(getattr(api, "_effective_proxy", "") or "")
        timeout_seconds = float(getattr(api, "_timeout_seconds", 60.0) or 60.0)
        retries = int(getattr(api, "_retries", 2) or 2)
        cookies_file = str(getattr(api, "_cookies_file", "") or "")
        cookies_from_browser = str(getattr(api, "_cookies_from_browser", "") or "")
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
            if text and text.strip():
                header = f"[yt-dlp | {label}]"
                return header + "\n\n" + text
        except Exception:
            pass

        if asr_enabled:
            label, text = transcribe_video_audio_with_ytdlp(
                video_url=video_url,
                proxy_url=proxy_url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                model_name=asr_model,
                language=asr_language,
            )
            return f"[asr | {label}]\n\n{text}"

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
    elif isinstance(e, FileNotFoundError) and ("ffmpeg" in raw_msg.lower() or "winerror 2" in raw_msg.lower()):
        msg = "未安装 ffmpeg（或未加入 PATH），无法进行音频转写。请先安装 ffmpeg 后重试。"
    elif ("could not copy" in raw_msg.lower() and "cookie" in raw_msg.lower()) or ("cookie database" in raw_msg.lower()):
        msg = "无法读取浏览器 Cookies（Cookie 数据库被占用/无权限）。建议关闭浏览器后重试，或改用 Edge/Firefox。"
    elif "HTTP Error 429" in raw_msg or "too many 429" in raw_msg.lower() or "429" in raw_msg:
        msg = "触发 YouTube 429 限流/风控。建议降低频率并等待一段时间，或使用更稳定的代理；也可启用“自动读取浏览器 Cookies”。"
    else:
        msg = str(e) or e.__class__.__name__

    msg = strip_ansi(msg)
    return f"失败原因：{msg}\n\n异常类型：{e.__class__.__name__}\n\n原始错误：{strip_ansi(repr(e))}"


def get_transcript_from_input(url_or_id: str, languages_csv: str) -> tuple[str, str, str]:
    video_url = normalize_youtube_url(url_or_id)
    video_id = extract_video_id(video_url)
    languages = [s.strip() for s in (languages_csv or "").split(",") if s.strip()]
    return video_id, video_url, ",".join(languages or ["zh-Hans", "zh", "en"])


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


def run_ui() -> None:
    root = tk.Tk()
    root.title("YouTube 字幕抓取验证")
    root.geometry("980x720")

    container = ttk.Frame(root, padding=12)
    container.pack(fill=tk.BOTH, expand=True)

    row1 = ttk.Frame(container)
    row1.pack(fill=tk.X)

    ttk.Label(row1, text="YouTube 链接或 11 位 ID").pack(side=tk.LEFT)
    url_var = tk.StringVar(value="https://www.youtube.com/watch?v=jNQXAC9IVRw")
    url_entry = ttk.Entry(row1, textvariable=url_var)
    url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    row2 = ttk.Frame(container)
    row2.pack(fill=tk.X, pady=(10, 0))

    ttk.Label(row2, text="语言优先级（逗号分隔）").pack(side=tk.LEFT)
    lang_var = tk.StringVar(value="zh-Hans,zh,en")
    lang_entry = ttk.Entry(row2, textvariable=lang_var)
    lang_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    row2b = ttk.Frame(container)
    row2b.pack(fill=tk.X, pady=(10, 0))

    ttk.Label(row2b, text="代理（可选，例：http://127.0.0.1:7890）").pack(side=tk.LEFT)
    proxy_var = tk.StringVar(value="")
    proxy_entry = ttk.Entry(row2b, textvariable=proxy_var)
    proxy_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    ttk.Label(row2b, text="超时(秒)").pack(side=tk.LEFT, padx=(12, 0))
    timeout_var = tk.StringVar(value="60")
    timeout_entry = ttk.Entry(row2b, textvariable=timeout_var, width=6)
    timeout_entry.pack(side=tk.LEFT, padx=(8, 0))

    ttk.Label(row2b, text="重试").pack(side=tk.LEFT, padx=(12, 0))
    retries_var = tk.StringVar(value="2")
    retries_entry = ttk.Entry(row2b, textvariable=retries_var, width=4)
    retries_entry.pack(side=tk.LEFT, padx=(8, 0))

    use_sys_proxy_var = tk.BooleanVar(value=True)
    use_sys_proxy_cb = ttk.Checkbutton(row2b, text="使用系统代理", variable=use_sys_proxy_var)
    use_sys_proxy_cb.pack(side=tk.LEFT, padx=(12, 0))

    row2d = ttk.Frame(container)
    row2d.pack(fill=tk.X, pady=(10, 0))

    auto_cookies_var = tk.BooleanVar(value=True)
    auto_cookies_cb = ttk.Checkbutton(row2d, text="自动读取浏览器 Cookies", variable=auto_cookies_var)
    auto_cookies_cb.pack(side=tk.LEFT)

    ttk.Label(row2d, text="浏览器").pack(side=tk.LEFT, padx=(12, 0))
    cookies_browser_var = tk.StringVar(value="chrome")
    cookies_browser_combo = ttk.Combobox(
        row2d,
        textvariable=cookies_browser_var,
        values=["chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi", "safari"],
        width=10,
        state="readonly",
    )
    cookies_browser_combo.pack(side=tk.LEFT, padx=(8, 0))

    row2e = ttk.Frame(container)
    row2e.pack(fill=tk.X, pady=(10, 0))

    asr_var = tk.BooleanVar(value=True)
    asr_cb = ttk.Checkbutton(row2e, text="无字幕时音频转写", variable=asr_var)
    asr_cb.pack(side=tk.LEFT)

    ttk.Label(row2e, text="模型").pack(side=tk.LEFT, padx=(12, 0))
    asr_model_var = tk.StringVar(value="base")
    asr_model_combo = ttk.Combobox(
        row2e,
        textvariable=asr_model_var,
        values=["tiny", "base", "small", "medium", "large"],
        width=10,
        state="readonly",
    )
    asr_model_combo.pack(side=tk.LEFT, padx=(8, 0))

    ttk.Label(row2e, text="语言").pack(side=tk.LEFT, padx=(12, 0))
    asr_lang_var = tk.StringVar(value="auto")
    asr_lang_combo = ttk.Combobox(
        row2e,
        textvariable=asr_lang_var,
        values=["auto", "zh", "en", "ja", "ko"],
        width=8,
        state="readonly",
    )
    asr_lang_combo.pack(side=tk.LEFT, padx=(8, 0))

    # --- AI 总结配置区 ---
    row_ai = ttk.Frame(container)
    row_ai.pack(fill=tk.X, pady=(10, 0))
    
    ttk.Label(row_ai, text="AI API Key").pack(side=tk.LEFT)
    api_key_var = tk.StringVar(value="")
    api_key_entry = ttk.Entry(row_ai, textvariable=api_key_var, show="*")
    api_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    ttk.Label(row_ai, text="Base URL (选填)").pack(side=tk.LEFT, padx=(12, 0))
    base_url_var = tk.StringVar(value="https://api.openai.com/v1")
    base_url_entry = ttk.Entry(row_ai, textvariable=base_url_var)
    base_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    ttk.Label(row_ai, text="Model").pack(side=tk.LEFT, padx=(12, 0))
    model_var = tk.StringVar(value="gpt-3.5-turbo")
    # 优化为 Combobox
    model_entry = ttk.Combobox(
        row_ai,
        textvariable=model_var,
        values=[
            "gpt-3.5-turbo",
            "gpt-4o",
            "gpt-4-turbo",
            "deepseek-chat",
            "deepseek-reasoner",
            "qwen-plus",
            "qwen-turbo",
            "moonshot-v1-8k",
        ],
        width=15,
    )
    model_entry.pack(side=tk.LEFT, padx=(8, 0))

    def do_refresh_models():
        api_key = api_key_var.get().strip()
        base_url = base_url_var.get().strip()
        proxy_url = proxy_var.get().strip()
        
        if not api_key:
            messagebox.showwarning("提示", "请先填写 API Key")
            return

        def worker():
            try:
                root.after(0, lambda: append_output(f"\n>>> 正在获取可用模型列表..."))
                models = fetch_available_models(api_key, base_url, proxy_url)
                if models:
                    root.after(0, lambda: model_entry.configure(values=models))
                    if models:
                         root.after(0, lambda: model_var.set(models[0]))
                    root.after(0, lambda: append_output(f"\n已更新模型列表 ({len(models)} 个)"))
                    root.after(0, lambda: messagebox.showinfo("成功", f"成功获取 {len(models)} 个模型"))
                else:
                    root.after(0, lambda: append_output(f"\n获取到的模型列表为空"))
            except Exception as e:
                root.after(0, lambda: append_output(f"\n获取模型失败: {e}"))
                root.after(0, lambda: messagebox.showerror("错误", str(e)))
            finally:
                root.after(0, lambda: set_busy(False))

        set_busy(True)
        threading.Thread(target=worker, daemon=True).start()

    refresh_models_btn = ttk.Button(row_ai, text="刷新", width=4, command=do_refresh_models)
    refresh_models_btn.pack(side=tk.LEFT, padx=(4, 0))

    auto_summary_var = tk.BooleanVar(value=True)
    auto_summary_cb = ttk.Checkbutton(row_ai, text="自动总结", variable=auto_summary_var)
    auto_summary_cb.pack(side=tk.LEFT, padx=(12, 0))

    summary_btn = ttk.Button(row_ai, text="生成总结")
    summary_btn.pack(side=tk.RIGHT, padx=(8, 0))
    # --------------------

    row3 = ttk.Frame(container)
    row3.pack(fill=tk.X, pady=(10, 0))

    status_var = tk.StringVar(value="就绪")
    status_label = ttk.Label(row3, textvariable=status_var)
    status_label.pack(side=tk.LEFT)

    open_btn = ttk.Button(row3, text="打开视频")
    open_btn.pack(side=tk.RIGHT, padx=(8, 0))

    detect_btn = ttk.Button(row3, text="检测字幕")
    detect_btn.pack(side=tk.RIGHT, padx=(8, 0))

    fetch_btn = ttk.Button(row3, text="抓取字幕")
    fetch_btn.pack(side=tk.RIGHT)

    clear_btn = ttk.Button(row3, text="清空")
    clear_btn.pack(side=tk.RIGHT, padx=(8, 0))

    out = ScrolledText(container, wrap=tk.WORD)
    out.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

    # --- 加载配置 ---
    cfg = load_config()
    if "url" in cfg: url_var.set(cfg["url"])
    if "proxy" in cfg: proxy_var.set(cfg["proxy"])
    if "api_key" in cfg: api_key_var.set(cfg["api_key"])
    if "base_url" in cfg: base_url_var.set(cfg["base_url"])
    if "model" in cfg: model_var.set(cfg["model"])
    if "browser" in cfg: cookies_browser_var.set(cfg["browser"])
    if "auto_summary" in cfg: auto_summary_var.set(cfg["auto_summary"])
    # ----------------

    def save_current_config():
        new_cfg = {
            "url": url_var.get(),
            "proxy": proxy_var.get(),
            "api_key": api_key_var.get(),
            "base_url": base_url_var.get(),
            "model": model_var.get(),
            "browser": cookies_browser_var.get(),
            "auto_summary": auto_summary_var.get(),
        }
        save_config(new_cfg)

    def set_busy(is_busy: bool) -> None:
        fetch_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        detect_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        clear_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        open_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        refresh_models_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL) # 新增
        summary_btn.configure(state=tk.DISABLED if is_busy else tk.NORMAL)  # 新增
        auto_summary_cb.configure(state=tk.DISABLED if is_busy else tk.NORMAL)  # 新增
        url_entry.configure(state="disabled" if is_busy else "normal")
        lang_entry.configure(state="disabled" if is_busy else "normal")
        proxy_entry.configure(state="disabled" if is_busy else "normal")
        auto_cookies_cb.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        cookies_browser_combo.configure(state="disabled" if is_busy else "readonly")
        asr_cb.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        asr_model_combo.configure(state="disabled" if is_busy else "readonly")
        asr_lang_combo.configure(state="disabled" if is_busy else "readonly")
        timeout_entry.configure(state="disabled" if is_busy else "normal")
        retries_entry.configure(state="disabled" if is_busy else "normal")
        use_sys_proxy_cb.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        api_key_entry.configure(state="disabled" if is_busy else "normal")  # 新增
        base_url_entry.configure(state="disabled" if is_busy else "normal")  # 新增
        model_entry.configure(state="disabled" if is_busy else "normal")    # 新增

    def set_output(text: str) -> None:
        out.delete("1.0", tk.END)
        out.insert(tk.END, text)
        out.see(tk.END)

    def append_output(text: str) -> None:
        current = out.get("1.0", tk.END).strip()
        if current:
            out.insert(tk.END, "\n\n" + ("-" * 40) + "\n\n")
        out.insert(tk.END, text)
        out.see(tk.END)

    def do_clear() -> None:
        set_output("")
        status_var.set("就绪")

    def do_open() -> None:
        url_or_id = url_var.get().strip()
        if not url_or_id:
            status_var.set("请输入链接或视频 ID")
            return
        webbrowser.open(normalize_youtube_url(url_or_id))

    def do_fetch() -> None:
        save_current_config()  # 保存配置
        url_or_id = url_var.get().strip()
        languages_csv = lang_var.get().strip()
        proxy_url = proxy_var.get().strip()
        auto_cookies = bool(auto_cookies_var.get())
        cookies_browser = cookies_browser_var.get().strip()
        asr_enabled = bool(asr_var.get())
        asr_model = asr_model_var.get().strip()
        asr_lang = asr_lang_var.get().strip()
        timeout_seconds = timeout_var.get().strip() or "15"
        retries = retries_var.get().strip() or "2"
        use_system_proxy = use_sys_proxy_var.get()
        if not url_or_id:
            status_var.set("请输入链接或视频 ID")
            return
        cookies_mode = f"browser:{cookies_browser}" if auto_cookies else "none"
        asr_mode = f"{'on' if asr_enabled else 'off'}({asr_model},{asr_lang})"
        set_output(
            "参数\n"
            f"- input: {url_or_id}\n"
            f"- proxy: {proxy_url or '(empty)'}\n"
            f"- use_system_proxy: {use_system_proxy}\n"
            f"- timeout_seconds: {timeout_seconds}\n"
            f"- retries: {retries}\n"
            f"- languages: {languages_csv or '(empty)'}\n"
            f"- cookies: {cookies_mode}\n"
            f"- asr: {asr_mode}"
        )

        def worker() -> None:
            try:
                root.after(0, lambda: append_output("正在检查网络连通性..."))
                
                # 在子线程做这步，避免卡 UI
                eff_proxy, pac_note = get_effective_proxy(proxy_url, use_system_proxy)
                if pac_note:
                    root.after(0, lambda: append_output(f"提示: {pac_note}"))
                
                root.after(0, lambda: append_output(f"当前使用的代理: {eff_proxy or '无 (直连)'}"))
                net_err = check_network(eff_proxy, timeout=5.0)
                if net_err:
                    msg = f"网络预检失败（但将尝试强制继续）：\n{net_err}"
                    root.after(0, lambda: append_output(msg))
                else:
                    root.after(0, lambda: append_output("网络预检通过 (Google/YouTube 可连通)"))

                root.after(0, lambda: append_output(">>> 开始获取字幕信息..."))
                video_id, video_url, languages_effective = get_transcript_from_input(url_or_id, languages_csv)
                api = build_api(
                    proxy_url=proxy_url,
                    timeout_seconds=float(timeout_seconds),
                    use_system_proxy=use_system_proxy,
                    retries=int(retries),
                )
                setattr(api, "_cookies_file", "")
                setattr(api, "_cookies_from_browser", cookies_browser if auto_cookies else "")
                setattr(api, "_asr_enabled", asr_enabled)
                setattr(api, "_asr_model", asr_model)
                setattr(api, "_asr_language", asr_lang)
                languages = [s.strip() for s in languages_effective.split(",") if s.strip()]
                
                root.after(0, lambda: append_output(f"正在调用 get_video_transcript (id={video_id})..."))
                text = get_video_transcript(api, video_id, video_url=video_url, languages=languages)
                
                root.after(0, lambda: status_var.set(f"完成：{video_id}"))
                root.after(0, lambda: set_output(text))
                
                # 自动总结逻辑
                if auto_summary_var.get():
                    if api_key_var.get().strip():
                        root.after(0, lambda: append_output(f"\n\n>>> 正在自动请求 AI 总结 ({model_var.get().strip()})..."))
                        try:
                            summary = summarize_text(
                                text, 
                                api_key_var.get().strip(), 
                                base_url_var.get().strip(), 
                                model_var.get().strip(),
                                proxy_var.get().strip()
                            )
                            root.after(0, lambda: append_output("\n\n" + summary))
                            root.after(0, lambda: status_var.set("自动总结完成"))
                        except Exception as e:
                            root.after(0, lambda: append_output(f"\n\n自动总结失败: {e}"))
                    else:
                         root.after(0, lambda: append_output("\n\n提示：已开启自动总结，但未填写 API Key，跳过总结。"))
            except Exception as e:
                tb = traceback.format_exc()
                root.after(0, lambda: status_var.set("失败"))
                err_msg = format_error(e) + "\n\nTraceback:\n" + strip_ansi(tb)
                root.after(0, lambda: append_output(err_msg))
                # 弹窗提示，确保用户看到
                root.after(0, lambda: messagebox.showerror("抓取失败", f"发生了错误：\n{strip_ansi(str(e))}\n\n详情请查看主界面日志。"))
            finally:
                root.after(0, lambda: set_busy(False))

        set_busy(True)
        status_var.set("抓取中...")
        threading.Thread(target=worker, daemon=True).start()

    def do_detect() -> None:
        save_current_config()  # 保存配置
        url_or_id = url_var.get().strip()
        proxy_url = proxy_var.get().strip()
        timeout_seconds = timeout_var.get().strip() or "15"
        retries = retries_var.get().strip() or "2"
        use_system_proxy = use_sys_proxy_var.get()
        if not url_or_id:
            status_var.set("请输入链接或视频 ID")
            return

        def worker() -> None:
            try:
                root.after(0, lambda: append_output("正在检查网络连通性..."))
                
                # 在子线程做这步，避免卡 UI
                eff_proxy, pac_note = get_effective_proxy(proxy_url, use_system_proxy)
                if pac_note:
                    root.after(0, lambda: append_output(f"提示: {pac_note}"))
                
                root.after(0, lambda: append_output(f"当前使用的代理: {eff_proxy or '无 (直连)'}"))
                net_err = check_network(eff_proxy, timeout=5.0)
                if net_err:
                    msg = f"网络预检失败（但将尝试强制继续）：\n{net_err}"
                    root.after(0, lambda: append_output(msg))
                else:
                    root.after(0, lambda: append_output("网络预检通过 (Google/YouTube 可连通)"))

                root.after(0, lambda: append_output(">>> 开始检测字幕列表..."))
                video_id, video_url, languages_effective = get_transcript_from_input(url_or_id, languages_csv)
                api = build_api(
                    proxy_url=proxy_url,
                    timeout_seconds=float(timeout_seconds),
                    use_system_proxy=use_system_proxy,
                    retries=int(retries),
                )
                report = list_available_transcripts(api, video_id)
                root.after(0, lambda: status_var.set(f"检测完成：{video_id}"))
                root.after(0, lambda: set_output(report))
            except Exception as e:
                root.after(0, lambda: status_var.set("检测失败"))
                err_msg = format_error(e)
                root.after(0, lambda: set_output(err_msg))
                # 弹窗提示
                root.after(0, lambda: messagebox.showerror("检测失败", f"发生了错误：\n{strip_ansi(str(e))}\n\n详情请查看主界面日志。"))
            finally:
                root.after(0, lambda: set_busy(False))

        set_busy(True)
        status_var.set("检测中...")
        threading.Thread(target=worker, daemon=True).start()

    def do_summary() -> None:
        save_current_config()  # 保存配置
        text = out.get("1.0", tk.END).strip()
        api_key = api_key_var.get().strip()
        base_url = base_url_var.get().strip()
        model = model_var.get().strip()
        proxy_url = proxy_var.get().strip()
        
        if not text:
            status_var.set("内容为空，无法总结")
            messagebox.showinfo("提示", "请先抓取字幕内容，然后再点击生成总结。")
            return
        
        if not api_key:
            status_var.set("缺少 API Key")
            messagebox.showwarning("提示", "请在上方输入框填写 AI API Key。")
            api_key_entry.focus_set()
            return

        def worker() -> None:
            try:
                root.after(0, lambda: append_output(f"\n\n>>> 正在请求 AI 总结 ({model})..."))
                summary = summarize_text(text, api_key, base_url, model, proxy_url)
                root.after(0, lambda: append_output("\n\n" + summary))
                root.after(0, lambda: status_var.set("总结完成"))
            except Exception as e:
                root.after(0, lambda: status_var.set("总结失败"))
                root.after(0, lambda: append_output(f"\n\n总结出错: {e}"))
            finally:
                root.after(0, lambda: set_busy(False))

        set_busy(True)
        status_var.set("正在生成总结...")
        threading.Thread(target=worker, daemon=True).start()

    fetch_btn.configure(command=do_fetch)
    detect_btn.configure(command=do_detect)
    clear_btn.configure(command=do_clear)
    open_btn.configure(command=do_open)
    summary_btn.configure(command=do_summary)
    url_entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    print("UI started", flush=True)
    run_ui()
