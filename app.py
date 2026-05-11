
import streamlit as st
import streamlit.components.v1 as components
import threading
import time
import traceback
import json
import os
import re
import hashlib
import html
import uuid
import calendar
import requests
from datetime import datetime, timedelta, time as dt_time
from core_logic import (
    get_effective_proxy,
    check_network,
    get_transcript_from_input,
    build_api,
    get_video_transcript,
    list_available_transcripts,
    format_error,
    strip_ansi,
    summarize_text,
    validate_document_upload,
    extract_document_text,
    extract_document_from_url,
    summarize_document_text,
    classify_document_for_fact_check,
    fact_check_document_claims,
    decide_video_fact_check_plan,
    fetch_available_models,
    get_channel_info,
    get_channel_recent_videos,
    search_channels,
    get_remote_worker_status,
    build_runtime_version_diagnostics,
)

# --- 常量定义 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "subscriptions.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
GUESTBOOK_FILE = os.path.join(BASE_DIR, "guestbook.json")
FEEDBACK_FILE = os.path.join(BASE_DIR, "feedback_reports.json")
BRIDGE_COMPONENT_DIR = os.path.join(BASE_DIR, "bridge_component")
BRIDGE_STORAGE_PREFIX = "yt_summary_bridge:"
BRIDGE_API_URL = str(os.environ.get("BRIDGE_API_URL", "https://youtube-summarize-bridge.onrender.com") or "").strip().rstrip("/")
BRIDGE_API_TOKEN = str(os.environ.get("BRIDGE_API_TOKEN", "") or "").strip()
DEFAULT_SUMMARY_MODEL = "Pro/MiniMaxAI/MiniMax-M2.5"
DEFAULT_FACT_CHECK_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

extension_bridge_reader = components.declare_component(
    "extension_bridge_reader",
    path=BRIDGE_COMPONENT_DIR,
)

@st.cache_resource
def _get_shared_lock():
    return threading.Lock()


@st.cache_resource
def _get_video_fact_check_runtime():
    return {
        "lock": threading.Lock(),
        "tasks": {},
        "result_cache": {},
    }


def get_render_build_info() -> dict[str, str]:
    """返回当前运行环境的 Render / Git 构建信息。"""

    def _clean_env(name: str) -> str:
        return str(os.environ.get(name, "") or "").strip()

    is_render = _clean_env("RENDER") == "true"
    deploy_id = (
        _clean_env("RENDER_DEPLOY_ID")
        or _clean_env("RENDER_BUILD_ID")
        or _clean_env("RENDER_INSTANCE_ID")
    )
    commit = _clean_env("RENDER_GIT_COMMIT")
    branch = _clean_env("RENDER_GIT_BRANCH")
    repo_slug = _clean_env("RENDER_GIT_REPO_SLUG")
    service_id = _clean_env("RENDER_SERVICE_ID")
    service_name = _clean_env("RENDER_SERVICE_NAME")
    service_type = _clean_env("RENDER_SERVICE_TYPE")
    external_url = _clean_env("RENDER_EXTERNAL_URL")

    return {
        "is_render": "yes" if is_render else "no",
        "deploy_id": deploy_id,
        "commit": commit,
        "commit_short": commit[:7] if commit else "",
        "branch": branch,
        "repo_slug": repo_slug,
        "service_id": service_id,
        "service_name": service_name,
        "service_type": service_type,
        "external_url": external_url,
    }

def load_json_file(filepath, default_value):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default_value
    return default_value

def save_json_file(filepath, data):
    with _get_shared_lock():
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings_safe():
    with _get_shared_lock():
        return load_json_file(SETTINGS_FILE, {})

def save_settings_safe(settings):
    with _get_shared_lock():
        save_json_file(SETTINGS_FILE, settings)


def _looks_like_siliconflow_base_url(base_url_value: str) -> bool:
    lowered = str(base_url_value or "").strip().lower()
    return "siliconflow" in lowered


def resolve_pipeline_models(
    settings_dict: dict | None = None,
    *,
    env: dict | None = None,
    base_url_value: str = "",
) -> tuple[str, str]:
    settings_dict = settings_dict or {}
    env = env or os.environ
    legacy_model = str(settings_dict.get("model") or "gpt-3.5-turbo").strip() or "gpt-3.5-turbo"
    default_summary_model = legacy_model
    default_fact_check_model = legacy_model
    if _looks_like_siliconflow_base_url(base_url_value):
        default_summary_model = DEFAULT_SUMMARY_MODEL
        default_fact_check_model = DEFAULT_FACT_CHECK_MODEL

    summary_model = (
        str(env.get("OPENAI_SUMMARY_MODEL", "") or "").strip()
        or str(settings_dict.get("summary_model") or "").strip()
        or str(env.get("OPENAI_MODEL", "") or "").strip()
        or default_summary_model
    )
    fact_check_model = (
        str(env.get("OPENAI_FACT_CHECK_MODEL", "") or "").strip()
        or str(settings_dict.get("fact_check_model") or "").strip()
        or default_fact_check_model
    )
    return summary_model, fact_check_model


def format_pipeline_model_label(summary_model_name: str, fact_check_model_name: str) -> str:
    summary_model_name = str(summary_model_name or "").strip() or "unknown"
    fact_check_model_name = str(fact_check_model_name or "").strip() or summary_model_name
    if summary_model_name == fact_check_model_name:
        return summary_model_name
    return f"总结:{summary_model_name} | 核查:{fact_check_model_name}"

def load_history():
    return load_json_file(HISTORY_FILE, [])

def save_history(history):
    save_json_file(HISTORY_FILE, history)

def load_guestbook():
    return load_json_file(GUESTBOOK_FILE, [])

def save_guestbook(guestbook):
    save_json_file(GUESTBOOK_FILE, guestbook)

def load_feedback_reports():
    return load_json_file(FEEDBACK_FILE, [])

def save_feedback_reports(reports):
    save_json_file(FEEDBACK_FILE, reports)

def append_feedback_report(report: dict):
    reports = load_feedback_reports()
    reports.insert(0, report)
    if len(reports) > 500:
        reports = reports[:500]
    save_feedback_reports(reports)

def _short_display(value: str, limit: int = 24) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."

def build_issue_diagnostics_snapshot(
    context_label: str,
    *,
    source_url: str = "",
    error_text: str = "",
    extra: dict | None = None,
) -> dict:
    render_info = get_render_build_info()
    bridge_meta = st.session_state.get("manual_bridge_meta") or {}
    return {
        "timestamp": _iso(_now()),
        "context": str(context_label or "").strip(),
        "source_url": str(source_url or "").strip(),
        "error_text": str(error_text or "").strip(),
        "render_commit": render_info.get("commit_short") or "local",
        "render_branch": render_info.get("branch") or "local",
        "render_deploy_id": render_info.get("deploy_id") or "",
        "render_service": render_info.get("service_name") or "",
        "runtime_diag": str(build_runtime_version_diagnostics() or "").strip(),
        "bg_task_id": str(st.session_state.get("bg_task_id") or "").strip(),
        "has_video_transcript": bool(st.session_state.get("transcript_text")),
        "has_video_summary": bool(st.session_state.get("summary_text")),
        "has_manual_summary": bool(st.session_state.get("manual_summary_text")),
        "bridge_meta": bridge_meta if isinstance(bridge_meta, dict) else {},
        "extra": extra or {},
    }

def format_issue_diagnostics_text(snapshot: dict) -> str:
    if not isinstance(snapshot, dict):
        return ""
    lines = [
        f"time={snapshot.get('timestamp') or ''}",
        f"context={snapshot.get('context') or ''}",
        f"commit={snapshot.get('render_commit') or 'local'}",
        f"branch={snapshot.get('render_branch') or 'local'}",
        f"deploy_id={snapshot.get('render_deploy_id') or 'n/a'}",
        f"service={snapshot.get('render_service') or 'n/a'}",
        f"source_url={snapshot.get('source_url') or ''}",
        f"bg_task_id={snapshot.get('bg_task_id') or ''}",
        f"runtime_diag={snapshot.get('runtime_diag') or ''}",
    ]
    error_text = str(snapshot.get("error_text") or "").strip()
    if error_text:
        lines.append(f"error={error_text}")
    bridge_meta = snapshot.get("bridge_meta") or {}
    if bridge_meta:
        lines.append(f"bridge_meta={json.dumps(bridge_meta, ensure_ascii=False, sort_keys=True)}")
    extra = snapshot.get("extra") or {}
    if extra:
        lines.append(f"extra={json.dumps(extra, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines).strip()

def render_copy_to_clipboard_button(label: str, text: str, key: str) -> None:
    button_id = f"copy_btn_{re.sub(r'[^a-zA-Z0-9_]+', '_', key)}"
    status_id = f"{button_id}_status"
    button_label = html.escape(str(label or "复制"))
    text_payload = json.dumps(str(text or ""), ensure_ascii=False)
    components.html(
        f"""
        <div style="display:flex;align-items:center;gap:8px;margin:0.1rem 0 0.4rem 0;">
          <button id="{button_id}" style="padding:0.35rem 0.8rem;border-radius:0.5rem;border:1px solid #d0d7de;background:#f6f8fa;cursor:pointer;">
            {button_label}
          </button>
          <span id="{status_id}" style="color:#57606a;font-size:0.9rem;"></span>
        </div>
        <script>
        const btn = document.getElementById("{button_id}");
        const status = document.getElementById("{status_id}");
        btn.addEventListener("click", async () => {{
          const clipboard = navigator.clipboard || (window.parent && window.parent.navigator && window.parent.navigator.clipboard);
          try {{
            await clipboard.writeText({text_payload});
            status.textContent = "已复制";
            setTimeout(() => status.textContent = "", 1500);
          }} catch (err) {{
            status.textContent = "复制失败，请手动复制下方文本";
          }}
        }});
        </script>
        """,
        height=42,
    )

def render_issue_report_box(
    context_label: str,
    *,
    source_url: str = "",
    error_text: str = "",
    extra: dict | None = None,
    key_prefix: str,
    expanded: bool = False,
    box_title: str = "诊断与问题上报",
) -> None:
    snapshot = build_issue_diagnostics_snapshot(
        context_label,
        source_url=source_url,
        error_text=error_text,
        extra=extra,
    )
    diag_text = format_issue_diagnostics_text(snapshot)
    with st.expander(box_title, expanded=expanded):
        st.caption("先复制诊断信息，再提交问题反馈；后续排查会更快。")
        render_copy_to_clipboard_button("复制诊断信息", diag_text, f"{key_prefix}_copy")
        st.text_area(
            "诊断信息预览",
            diag_text,
            height=180,
            key=f"{key_prefix}_diag_preview",
        )
        with st.form(f"{key_prefix}_feedback_form", clear_on_submit=True):
            reporter = st.text_input("昵称", value="User", max_chars=20)
            issue_type = st.selectbox(
                "问题类型",
                ["提取失败", "总结失败", "事实核查问题", "版本/部署问题", "其他"],
                key=f"{key_prefix}_issue_type",
            )
            report_source_url = st.text_input(
                "来源链接（可选）",
                value=str(source_url or ""),
                key=f"{key_prefix}_source_url",
            )
            report_message = st.text_area(
                "问题描述",
                value=str(error_text or ""),
                height=120,
                placeholder="请尽量描述你做了什么、预期是什么、实际发生了什么。",
                key=f"{key_prefix}_message",
            )
            submitted = st.form_submit_button("提交问题")
            if submitted:
                append_feedback_report(
                    {
                        "id": str(uuid.uuid4()),
                        "timestamp": _iso(_now()),
                        "user": reporter.strip() or "Anonymous",
                        "issue_type": issue_type,
                        "context": context_label,
                        "source_url": report_source_url.strip(),
                        "message": report_message.strip(),
                        "diagnostics": snapshot,
                        "diagnostics_text": diag_text,
                    }
                )
                st.success("问题已记录，可继续把上面的诊断信息直接发给我或测试群。")

def read_extension_bridge_payload(payload_id: str, consume: bool = True) -> dict | None:
    """从主站同域 bridge storage 读取扩展预先写入的 transcript 载荷。"""
    if not payload_id:
        return None

    payload = extension_bridge_reader(
        payloadId=payload_id,
        storageKeyPrefix=BRIDGE_STORAGE_PREFIX,
        consume=consume,
        height=0,
        key=f"extension_bridge_{payload_id}",
        default=None,
    )
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    return payload if isinstance(payload, dict) else None


def fetch_extension_bridge_payload(payload_id: str, consume: bool = True) -> tuple[dict | None, str]:
    """优先从独立 bridge API 拉取 payload，失败时返回错误原因。"""
    if not payload_id:
        return None, "payload_id_required"
    if not BRIDGE_API_URL:
        return None, "bridge_api_url_missing"

    try:
        headers = {}
        if BRIDGE_API_TOKEN:
            headers["X-Bridge-Token"] = BRIDGE_API_TOKEN
        response = requests.get(
            f"{BRIDGE_API_URL}/api/bridge/payload",
            params={"payload_id": payload_id, "consume": "1" if consume else "0"},
            headers=headers,
            timeout=3,
        )
        payload = response.json()
    except Exception as exc:
        return None, f"bridge_api_request_failed:{type(exc).__name__}"

    if response.status_code != 200 or not isinstance(payload, dict) or not payload.get("ok"):
        return None, str((payload or {}).get("error") or f"http_{response.status_code}")

    result = payload.get("payload")
    return result if isinstance(result, dict) else None, ""


def wait_for_extension_bridge_payload(payload_id: str) -> tuple[dict | None, str]:
    """短轮询 bridge API，兼顾 Render 冷启动和上传完成时序。"""
    last_error = ""
    for attempt in range(4):
        consume = attempt == 3
        payload, error = fetch_extension_bridge_payload(payload_id, consume=consume)
        bridge_transcript = str((payload or {}).get("transcript") or "").strip() if isinstance(payload, dict) else ""
        if bridge_transcript:
            return payload, ""

        last_error = error or last_error
        # payload_not_found 时多给几次机会，避免扩展刚上传完成前主站抢先查询
        if error == "payload_not_found" and attempt < 3:
            time.sleep(0.45)
            continue
        break

    return None, last_error


def request_extension_summarize_flow(
    source_url: str,
    request_id: str = "",
    component_key: str = "",
) -> dict | None:
    """通过隐藏组件向页面内插件发起抓取请求，成功时返回 payloadId。"""
    source_url = str(source_url or "").strip()
    if not source_url:
        return None
    request_id = str(request_id or "").strip() or f"video_extension_request_{uuid.uuid4().hex}"
    component_key = str(component_key or "").strip() or f"video_extension_request_{request_id}"
    return extension_bridge_reader(
        action="requestExtensionSummarize",
        sourceUrl=source_url,
        requestId=request_id,
        timeoutMs=150000,
        height=0,
        key=component_key,
        default=None,
    )


def normalize_extension_request_result(result) -> dict | None:
    """兼容组件返回的空字符串/JSON 字符串，避免把异步初始态误判为失败。"""
    if result is None or isinstance(result, dict):
        return result

    if isinstance(result, str):
        text = result.strip()
        if not text or text.lower() in {"none", "null", "undefined"}:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return {
                "ok": False,
                "error": f"unexpected_component_value:{text[:120]}",
            }
        return parsed if isinstance(parsed, dict) else {
            "ok": False,
            "error": "unexpected_component_value_non_object",
        }

    return {
        "ok": False,
        "error": f"unexpected_component_type:{type(result).__name__}",
    }


def normalize_extension_bridge_payload(payload: dict | None) -> dict:
    """兼容 bridge V1/V2，统一返回主站消费字段。"""
    if not isinstance(payload, dict):
        return {
            "payload_id": "",
            "bridge_version": 1,
            "tool_version": "",
            "source_url": "",
            "title": "",
            "transcript_text": "",
            "request_id": "",
            "source_kind": "",
            "source_type": "",
            "fallback_used": False,
            "text_source_reason": "",
            "envelope": None,
        }

    envelope = payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None
    transcript_obj = envelope.get("transcript") if isinstance(envelope, dict) and isinstance(envelope.get("transcript"), dict) else {}
    video_obj = envelope.get("video") if isinstance(envelope, dict) and isinstance(envelope.get("video"), dict) else {}
    source_obj = envelope.get("source") if isinstance(envelope, dict) and isinstance(envelope.get("source"), dict) else {}
    diagnostics_obj = envelope.get("diagnostics") if isinstance(envelope, dict) and isinstance(envelope.get("diagnostics"), dict) else {}

    transcript_text = str(transcript_obj.get("text") or payload.get("transcript") or "").strip()
    source_url = str(video_obj.get("url") or payload.get("sourceUrl") or payload.get("source_url") or "").strip()
    title = str(video_obj.get("title") or payload.get("title") or "").strip()
    payload_id = str(payload.get("payloadId") or payload.get("payload_id") or "").strip()
    bridge_version = int(payload.get("bridgeVersion") or payload.get("bridge_version") or (2 if envelope else 1) or 1)
    request_id = str(payload.get("requestId") or payload.get("request_id") or (envelope or {}).get("requestId") or "").strip()
    source_kind = str(payload.get("sourceKind") or payload.get("source_kind") or source_obj.get("kind") or "").strip()
    source_type = str(payload.get("sourceType") or payload.get("source_type") or source_obj.get("sourceType") or "").strip()
    tool_version = str(payload.get("toolVersion") or payload.get("tool_version") or source_obj.get("toolVersion") or "").strip()
    fallback_used = bool(payload.get("fallbackUsed") if "fallbackUsed" in payload else payload.get("fallback_used"))
    text_source_reason = str(payload.get("textSourceReason") or payload.get("text_source_reason") or diagnostics_obj.get("textSourceReason") or "").strip()
    if not fallback_used:
        fallback_used = bool(diagnostics_obj.get("fallbackUsed"))

    return {
        "payload_id": payload_id,
        "bridge_version": bridge_version,
        "tool_version": tool_version,
        "source_url": source_url,
        "title": title,
        "transcript_text": transcript_text,
        "request_id": request_id,
        "source_kind": source_kind,
        "source_type": source_type,
        "fallback_used": fallback_used,
        "text_source_reason": text_source_reason,
        "envelope": envelope,
    }


def format_manual_bridge_meta(meta: dict | None) -> str:
    """将主站接收到的 bridge 元信息格式化成可读提示。"""
    if not isinstance(meta, dict):
        return ""

    bits: list[str] = []
    source_kind = str(meta.get("source_kind") or "").strip()
    source_type = str(meta.get("source_type") or "").strip()
    bridge_version = str(meta.get("bridge_version") or "").strip()
    tool_version = str(meta.get("tool_version") or "").strip()
    request_id = str(meta.get("request_id") or "").strip()
    fallback_used = bool(meta.get("fallback_used"))

    if source_kind:
        bits.append(f"来源端：`{source_kind}`")
    if source_type:
        bits.append(f"文本类型：`{source_type}`")
    if bridge_version:
        bits.append(f"bridge 版本：`v{bridge_version}`")
    if tool_version:
        bits.append(f"扩展版本：`v{tool_version}`")
    if request_id:
        bits.append(f"requestId：`{request_id}`")
    if fallback_used:
        bits.append("兜底链路：`是`")
    return " | ".join(bits)


def build_manual_bridge_context(meta: dict | None) -> dict:
    """将 bridge 元信息转成主站可直接展示的用户态说明。"""
    if not isinstance(meta, dict):
        return {"summary": "", "details": ""}

    source_kind = str(meta.get("source_kind") or "").strip()
    source_type = str(meta.get("source_type") or "").strip()
    title = str(meta.get("title") or "").strip()
    text_source_reason = str(meta.get("text_source_reason") or "").strip()
    fallback_used = bool(meta.get("fallback_used"))

    source_kind_label = {
        "extension": "浏览器扩展",
        "local_tool": "本地转写助手",
    }.get(source_kind, "外部文本")

    source_type_label = {
        "subtitle": "公开字幕",
        "transcript": "公开 transcript",
        "local_asr": "本地语音转写",
    }.get(source_type, "文本")

    if source_kind == "local_tool" or fallback_used:
        summary = f"当前文本来自{source_kind_label}，属于兜底转写链路。"
    elif source_kind == "extension":
        summary = f"当前文本来自{source_kind_label}直接提取，无需本地转写。"
    else:
        summary = f"当前文本来源已接入主站，类型为{source_type_label}。"

    details: list[str] = [f"文本类型：`{source_type_label}`"]
    if title:
        details.append(f"标题：`{title}`")

    if text_source_reason == "no_text_source_found":
        details.append("触发原因：页面没有可直接提取的公开文本")
    elif text_source_reason == "extract_failed":
        details.append("触发原因：本次更像是提取失败")
    elif text_source_reason == "page_not_supported":
        details.append("触发原因：当前页面暂不支持")

    return {
        "summary": summary,
        "details": " | ".join(details),
    }


@st.cache_data(ttl=8, show_spinner=False)
def get_remote_worker_status_cached(refresh_key: int = 0):
    return get_remote_worker_status(timeout_seconds=4.0)

def add_history_entry(source_type, video_url, summary_text, transcript_text=""):
    history = load_history()
    # 尝试解析摘要中的标题 (如果可能)
    title = "未命名视频"
    # 简单尝试从 summary 中提取标题 (假设 JSON 格式)
    try:
        if summary_text.strip().startswith("{"):
            data = json.loads(summary_text)
            # 尝试从 markdown 中提取第一行作为标题
            md = data.get("summary_markdown", "")
            lines = md.split("\n")
            for line in lines:
                if "核心主题" in line or "核心一句话" in line:
                    continue
                if line.strip() and not line.startswith("#"):
                    title = line.strip()
                    break
    except:
        pass
    
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": _iso(_now()),
        "source_type": source_type, # 'single' or 'schedule'
        "video_url": video_url,
        "title": title,
        "summary_text": summary_text,
        # "transcript_text": transcript_text[:1000] + "..." if transcript_text else "" # 可选：为了省空间只存摘要
    }
    history.insert(0, entry) # 插入到开头
    # 限制历史记录数量，例如保留最近 500 条
    if len(history) > 500:
        history = history[:500]
    save_history(history)


def _extract_whisper_device_info(text: str) -> tuple[str, str]:
    """从字幕文本里提取 FW_DEVICE 标签，并返回清理后的正文。"""
    text = text or ""
    match = re.search(r"<!-- FW_DEVICE: (.*?) -->", text)
    device_info = match.group(1).strip() if match else ""
    cleaned = re.sub(r"\n*\s*<!-- FW_DEVICE: .*? -->", "", text)
    return device_info, cleaned.strip()


def _clean_transcript_for_display(text: str) -> str:
    """清理内部标签，并把 ASR 长串文本整理成更适合阅读的段落。"""
    _, cleaned = _extract_whisper_device_info(text or "")
    cleaned = re.sub(r"\n*\s*<!-- TIMING: .*? -->", "", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return ""

    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.splitlines()]
        lines = [line for line in lines if line]
        return "\n\n".join(lines)

    # 对 ASR 连续文本做温和断句，避免一大坨难以阅读
    punctuated = re.sub(r"([。！？!?；;])", r"\1\n", cleaned)
    punctuated = re.sub(r"([，,])", r"\1 ", punctuated)
    punctuated = re.sub(r"\n{2,}", "\n", punctuated)
    segments = [seg.strip() for seg in punctuated.split("\n") if seg.strip()]
    return "\n\n".join(segments)


def _raw_transcript_for_display(text: str) -> str:
    """保留原始正文，只去掉内部调试标签，便于排查。"""
    _, cleaned = _extract_whisper_device_info(text or "")
    cleaned = re.sub(r"\n*\s*<!-- TIMING: .*? -->", "", cleaned)
    return cleaned.strip()


def _parse_summary_for_ui(summary_text: str) -> tuple[str, str]:
    """尽量把模型返回的 JSON/伪 JSON 拆成总结与事实核查两部分。"""
    text = (summary_text or "").strip()
    if not text:
        return "", ""

    def _extract_field(raw: str, field_names: list[str]) -> str:
        for field_name in field_names:
            pattern = rf'"{re.escape(field_name)}"\s*:\s*("(?:\\.|[^"\\])*")'
            match = re.search(pattern, raw, re.S)
            if not match:
                continue
            try:
                value = json.loads(match.group(1))
                return str(value or "").strip()
            except Exception:
                continue
        return ""

    candidates = [text]
    if text.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", text)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
        candidates.append(stripped)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    continue
            if isinstance(data, dict):
                summary_md = str(data.get("summary_markdown") or data.get("summary") or "").strip()
                fact_md = str(
                    data.get("fact_check_markdown")
                    or data.get("fact_check")
                    or data.get("factcheck_markdown")
                    or ""
                ).strip()
                if summary_md:
                    return summary_md, fact_md
        except Exception:
            continue

    summary_md = _extract_field(text, ["summary_markdown", "summary", "summary_md"])
    fact_md = _extract_field(text, ["fact_check_markdown", "fact_check", "factcheck_markdown", "fact_check_md"])
    if summary_md:
        return summary_md, fact_md

    return "", ""


def _extract_markdown_links(markdown_text: str) -> list[tuple[str, str]]:
    """提取 Markdown 链接，供来源卡片渲染复用。"""
    return [
        (str(label or "").strip(), str(url or "").strip())
        for label, url in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", str(markdown_text or ""))
        if str(label or "").strip() and str(url or "").strip()
    ]


def _split_fact_check_sections(fact_check_md: str) -> list[str]:
    """按条目拆分事实核查结果，兼容标题块和编号列表两种格式。"""
    text = str(fact_check_md or "").strip()
    if not text:
        return []
    parts = re.split(
        r"(?=^(?:###\s*条目\d+|\d+\.\s*(?:新闻/声明|关键声明|声明|新闻)[:：]))",
        text,
        flags=re.M,
    )
    return [part.strip() for part in parts if part and part.strip()]


def _parse_fact_check_section(section_text: str) -> dict[str, object]:
    """解析单条事实核查，拆出标题、结论、依据、待补充项和来源。"""
    section = str(section_text or "").strip()
    lines = [line.rstrip() for line in section.splitlines()]
    title = ""
    conclusion = ""
    rationale_lines: list[str] = []
    pending_lines: list[str] = []
    body_lines: list[str] = []
    source_lines: list[str] = []
    active_field = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if active_field in {"rationale", "pending"}:
                target = rationale_lines if active_field == "rationale" else pending_lines
                if target and target[-1] != "":
                    target.append("")
            continue
        if not title:
            claim_match = re.search(r"(?:新闻/声明|关键声明|声明|新闻)[:：]\s*(.+)", stripped)
            if claim_match:
                title = claim_match.group(1).strip()
                active_field = ""
                continue
            elif stripped.startswith("###"):
                title = stripped.lstrip("#").strip()
                active_field = ""
                continue
        conclusion_match = re.search(r"核查结论[:：]\s*(.+)", stripped)
        if conclusion_match and not conclusion:
            conclusion = conclusion_match.group(1).strip()
            active_field = ""
            continue
        rationale_match = re.search(r"(?:判断依据|依据)[:：]\s*(.*)", stripped)
        if rationale_match:
            rationale_text = rationale_match.group(1).strip()
            if rationale_text:
                rationale_lines.append(rationale_text)
            active_field = "rationale"
            continue
        pending_match = re.search(r"待补充核查点[:：]\s*(.*)", stripped)
        if pending_match:
            pending_text = pending_match.group(1).strip()
            if pending_text:
                pending_lines.append(pending_text)
            active_field = "pending"
            continue
        if re.search(r"来源(?:链接|/出处|出处)?[:：]", stripped):
            source_lines.append(stripped)
            active_field = ""
            continue
        if active_field == "rationale":
            rationale_lines.append(stripped)
            continue
        if active_field == "pending":
            pending_lines.append(stripped)
            continue
        body_lines.append(line)

    if not title:
        title = "事实核查"

    source_links = _extract_markdown_links(section)
    body_markdown = "\n".join(body_lines).strip()
    rationale_markdown = "\n".join(line for line in rationale_lines).strip()
    pending_markdown = "\n".join(line for line in pending_lines).strip()
    source_summary = "\n".join(source_lines).strip()
    return {
        "title": title,
        "conclusion": conclusion,
        "rationale_markdown": rationale_markdown,
        "pending_markdown": pending_markdown,
        "body_markdown": body_markdown,
        "source_links": source_links,
        "source_summary": source_summary,
    }


def _render_fact_check_label(label: str) -> None:
    st.markdown(
        (
            "<div style='margin:0.55rem 0 0.2rem 0;"
            "font-size:0.8rem;font-weight:600;color:#57606a;'>"
            f"{html.escape(str(label or '').strip())}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_source_links(source_links: list[tuple[str, str]]) -> None:
    """将来源列表渲染为简洁链接列表。"""
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in source_links:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append((str(label or "").strip() or normalized, normalized))
    if not deduped:
        st.caption("当前未提取到可点击的核查来源。")
        return
    _render_fact_check_label("来源/出处")
    source_lines = [f"- [{label}]({url})" for label, url in deduped[:12]]
    st.markdown("\n".join(source_lines))


def render_fact_check_content(fact_check_md: str, *, fact_title: str = "🕵️ 事实核查") -> None:
    """渲染简洁版事实核查正文与来源链接。"""
    text = str(fact_check_md or "").strip()
    if not text:
        return
    st.markdown(f"### {fact_title}")

    sections = _split_fact_check_sections(text)
    if not sections:
        st.markdown(text)
        return

    for idx, section in enumerate(sections, start=1):
        parsed = _parse_fact_check_section(section)
        title = str(parsed.get("title") or f"条目 {idx}")
        conclusion = str(parsed.get("conclusion") or "").strip()
        st.markdown(f"#### {title}")
        if conclusion:
            st.markdown(
                (
                    "<div style='margin:0.25rem 0 0.75rem 0;padding:0.6rem 0.8rem;"
                    "border:1px solid #d0d7de;border-radius:0.75rem;background:#f6f8fa;'>"
                    "<div style='font-size:0.8rem;font-weight:600;color:#57606a;margin-bottom:0.2rem;'>核查结论</div>"
                    f"<div style='color:#24292f;'>{html.escape(conclusion)}</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
        rationale_markdown = str(parsed.get("rationale_markdown") or "").strip()
        if rationale_markdown:
            _render_fact_check_label("判断依据")
            st.markdown(rationale_markdown)
        pending_markdown = str(parsed.get("pending_markdown") or "").strip()
        if pending_markdown:
            _render_fact_check_label("待补充核查点")
            st.markdown(pending_markdown)
        body_markdown = str(parsed.get("body_markdown") or "").strip()
        if body_markdown:
            st.markdown(body_markdown)
        _render_source_links(list(parsed.get("source_links") or []))
        source_summary = str(parsed.get("source_summary") or "").strip()
        if source_summary and not parsed.get("source_links"):
            st.caption(source_summary)
        if idx < len(sections):
            st.divider()


def render_summary_fact_check(
    summary_md: str,
    fact_check_md: str,
    *,
    fact_title: str = "🕵️ 事实核查",
    summary_tab_label: str = "📝 核心总结",
    fact_tab_label: str = "🕵️ 事实核查",
) -> None:
    """统一渲染总结与事实核查，优先使用同页左右布局。"""
    has_fact_check = bool(str(fact_check_md or "").strip())
    if not has_fact_check:
        st.markdown(f"### {summary_tab_label}")
        st.markdown(summary_md)
        return

    col_sum, col_check = st.columns([1.15, 0.95], gap="large")
    with col_sum:
        st.markdown(f"### {summary_tab_label}")
        st.markdown(summary_md)
    with col_check:
        render_fact_check_content(fact_check_md, fact_title=fact_title)


def render_summary_content(
    summary_content: str,
    *,
    fact_title: str = "🕵️ 事实核查",
    fact_tab_label: str = "🕵️ 事实核查",
) -> None:
    """
    统一处理总结内容展示，兼容结构化 JSON 总结和旧版纯文本总结。
    """
    summary_md, fact_check_md = _parse_summary_for_ui(summary_content)
    if summary_md:
        render_summary_fact_check(
            summary_md,
            fact_check_md,
            fact_title=fact_title,
            fact_tab_label=fact_tab_label,
        )
    else:
        st.markdown(summary_content)


def update_settings_partial(patch):
    with _get_shared_lock():
        settings = load_settings()
        if not isinstance(settings, dict):
            settings = {}
        settings.update(patch)
        save_settings(settings)

def _now():
    return datetime.now()

def _iso(dt_value):
    if not dt_value:
        return ""
    return dt_value.isoformat()

def _parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def _parse_time_value(time_value):
    if isinstance(time_value, datetime):
        return time_value.time()
    if hasattr(time_value, "hour") and hasattr(time_value, "minute"):
        try:
            return dt_time(hour=int(time_value.hour), minute=int(time_value.minute))
        except Exception:
            return None
    if isinstance(time_value, str):
        parts = time_value.strip().split(":")
        if len(parts) >= 2:
            try:
                return dt_time(hour=int(parts[0]), minute=int(parts[1]))
            except Exception:
                return None
    return None

def _parse_cron_field(field, min_value, max_value):
    if not field or field.strip() == "*":
        return list(range(min_value, max_value + 1))
    values = []
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            val = int(part)
            if min_value <= val <= max_value:
                values.append(val)
    return sorted(set(values))

def _next_cron_time(base_time, cron_expr):
    parts = (cron_expr or "").split()
    if len(parts) != 5:
        return None
    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    days = _parse_cron_field(parts[2], 1, 31)
    months = _parse_cron_field(parts[3], 1, 12)
    weekdays = _parse_cron_field(parts[4], 0, 6)
    if not minutes or not hours or not days or not months or not weekdays:
        return None
    cursor = base_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_minutes = 60 * 24 * 180
    for _ in range(max_minutes):
        if (cursor.minute in minutes and cursor.hour in hours and cursor.day in days and cursor.month in months and cursor.weekday() in weekdays):
            return cursor
        cursor += timedelta(minutes=1)
    return None

def _compute_next_run(task, base_time):
    schedule_type = (task.get("schedule_type") or "daily").lower()
    if schedule_type == "interval":
        interval_hours = int(task.get("interval_hours") or 0)
        if interval_hours <= 0:
            return None
        base_anchor = _parse_iso(task.get("last_run_at")) or _parse_iso(task.get("created_at")) or base_time
        if base_anchor > base_time:
            return base_anchor
        delta_seconds = (base_time - base_anchor).total_seconds()
        interval_seconds = interval_hours * 3600
        steps = int(delta_seconds // interval_seconds) + 1
        return base_anchor + timedelta(seconds=steps * interval_seconds)
    time_value = _parse_time_value(task.get("time"))
    if schedule_type == "daily":
        if not time_value:
            return None
        candidate = base_time.replace(hour=time_value.hour, minute=time_value.minute, second=0, microsecond=0)
        if candidate <= base_time:
            candidate += timedelta(days=1)
        return candidate
    if schedule_type == "weekly":
        if not time_value:
            return None
        weekdays = task.get("weekdays") or []
        if not weekdays:
            return None
        weekdays = sorted({int(x) for x in weekdays if str(x).isdigit()})
        candidate = base_time.replace(hour=time_value.hour, minute=time_value.minute, second=0, microsecond=0)
        for add_days in range(0, 8):
            test_day = candidate + timedelta(days=add_days)
            if test_day.weekday() in weekdays and test_day > base_time:
                return test_day
        return None
    if schedule_type == "cron":
        return _next_cron_time(base_time, task.get("cron") or "")
    return None

def _normalize_task(task):
    now_iso = _iso(_now())
    normalized = {
        "id": task.get("id") or str(uuid.uuid4()),
        "channel_id": task.get("channel_id") or "",
        "channel_name": task.get("channel_name") or "",
        "channel_url": task.get("channel_url") or "",
        "platform": task.get("platform") or "",
        "schedule_type": task.get("schedule_type") or "daily",
        "time": task.get("time") or "09:00",
        "weekdays": task.get("weekdays") or [],
        "cron": task.get("cron") or "",
        "interval_hours": task.get("interval_hours") or 0,
        "enabled": bool(task.get("enabled", True)),
        "created_at": task.get("created_at") or now_iso,
        "last_run_at": task.get("last_run_at") or "",
        "next_run_at": task.get("next_run_at") or "",
        "retry_count": int(task.get("retry_count") or 0),
        "next_retry_at": task.get("next_retry_at") or "",
        "max_items": int(task.get("max_items") or 5),
        "min_duration_seconds": int(task.get("min_duration_seconds") or 0),
        "only_streams": bool(task.get("only_streams") or False),
        "last_error": task.get("last_error") or "",
    }
    return normalized

def _load_scheduled_state():
    with _get_shared_lock():
        settings = load_settings()
    tasks = settings.get("scheduled_tasks") or []
    tasks = [_normalize_task(t) for t in tasks if isinstance(t, dict)]
    logs = settings.get("schedule_logs") or []
    runs = settings.get("scheduled_runs") or []
    run_items = settings.get("scheduled_run_items") or []
    processed_ids = settings.get("scheduled_processed_ids") or []
    if not isinstance(runs, list):
        runs = []
    if not isinstance(run_items, list):
        run_items = []
    if not isinstance(processed_ids, list):
        processed_ids = []
    return settings, tasks, logs, runs, run_items, processed_ids

def _save_scheduled_state(settings_ignored, tasks, logs, runs, run_items, processed_ids):
    # settings_ignored 参数被忽略，我们重新加载最新的 settings 以避免覆盖其他字段
    with _get_shared_lock():
        current = load_settings()
        if not isinstance(current, dict):
            current = {}
        current["scheduled_tasks"] = tasks
        current["schedule_logs"] = logs[-200:]
        current["scheduled_runs"] = runs[-200:]
        current["scheduled_run_items"] = run_items[-1000:]
        if isinstance(processed_ids, set):
            processed_list = list(processed_ids)
        else:
            processed_list = list(dict.fromkeys(processed_ids or []))
        current["scheduled_processed_ids"] = processed_list
        save_settings(current)


def _append_log(logs, level, message, task_id=""):
    logs.append({
        "time": _iso(_now()),
        "level": level,
        "message": message,
        "task_id": task_id,
    })

def _trim_schedule_records(runs, run_items, max_runs=200, max_items=1000):
    runs_sorted = sorted(runs, key=lambda r: r.get("triggered_at") or "", reverse=True)
    runs_sorted = runs_sorted[:max_runs]
    run_ids = {r.get("id") for r in runs_sorted if r.get("id")}
    items_filtered = [i for i in run_items if i.get("run_id") in run_ids]
    items_filtered = items_filtered[:max_items]
    return runs_sorted, items_filtered

def _format_run_status(status):
    status_map = {
        "success": "成功",
        "partial": "部分成功",
        "failed": "失败",
        "no_update": "无新增",
        "running": "进行中",
    }
    return status_map.get(status or "", "未知")

def _format_time_label(dt_value):
    if not dt_value:
        return "—"
    return dt_value.strftime("%Y-%m-%d %H:%M")

def _group_runs_by_day(runs, run_items):
    day_map = {}
    items_by_run = {}
    for item in run_items:
        run_id = item.get("run_id")
        if run_id:
            items_by_run.setdefault(run_id, []).append(item)
    for run in runs:
        triggered = _parse_iso(run.get("triggered_at"))
        if not triggered:
            continue
        day_key = triggered.strftime("%Y-%m-%d")
        day_entry = day_map.setdefault(day_key, {
            "date": day_key,
            "runs": [],
            "new_items": 0,
            "success_items": 0,
            "failed_items": 0,
        })
        day_entry["runs"].append(run)
        day_entry["new_items"] += int(run.get("new_items") or 0)
        day_entry["success_items"] += int(run.get("success_items") or 0)
        day_entry["failed_items"] += int(run.get("failed_items") or 0)
    days = sorted(day_map.values(), key=lambda d: d.get("date") or "", reverse=True)
    return days, items_by_run

def _group_items_by_day(run_items):
    day_map = {}
    items_by_day = {}
    for item in run_items:
        created_at = _parse_iso(item.get("created_at"))
        if not created_at:
            continue
        day_key = created_at.strftime("%Y-%m-%d")
        items_by_day.setdefault(day_key, []).append(item)
        day_entry = day_map.setdefault(day_key, {
            "date": day_key,
            "total_items": 0,
            "success_items": 0,
            "failed_items": 0,
        })
        day_entry["total_items"] += 1
        if item.get("status") == "success":
            day_entry["success_items"] += 1
        elif item.get("status") == "failed":
            day_entry["failed_items"] += 1
    days = sorted(day_map.values(), key=lambda d: d.get("date") or "", reverse=True)
    return days, items_by_day

def _task_conflict(existing_tasks, new_task):
    for t in existing_tasks:
        if t.get("channel_id") != new_task.get("channel_id"):
            continue
        if t.get("schedule_type") == "weekly" and new_task.get("schedule_type") == "weekly":
            if t.get("time") == new_task.get("time"):
                overlap = set(t.get("weekdays") or []) & set(new_task.get("weekdays") or [])
                if overlap:
                    return True
        if t.get("schedule_type") == "daily" and new_task.get("schedule_type") == "daily":
            if t.get("time") == new_task.get("time"):
                return True
        if t.get("schedule_type") == "cron" and new_task.get("schedule_type") == "cron":
            if (t.get("cron") or "").strip() == (new_task.get("cron") or "").strip():
                return True
        if t.get("schedule_type") == "interval" and new_task.get("schedule_type") == "interval":
            if int(t.get("interval_hours") or 0) == int(new_task.get("interval_hours") or 0):
                return True
    return False

def _run_task_once(task, settings):
    logs = settings.get("schedule_logs") or []
    runs = settings.get("scheduled_runs") or []
    run_items = settings.get("scheduled_run_items") or []
    processed_ids = settings.get("scheduled_processed_ids") or []
    processed_set = set(processed_ids)
    proxy_value = settings.get("proxy", "")
    eff_proxy, _ = get_effective_proxy(proxy_value, True)
    timeout_seconds = float(settings.get("timeout_seconds") or 20.0)
    channel_url = task.get("channel_url")
    summary_model_name, fact_check_model_name = resolve_pipeline_models(
        settings,
        base_url_value=str(settings.get("base_url") or ""),
    )
    if not channel_url:
        _append_log(logs, "error", "任务缺少频道链接，已跳过", task.get("id"))
        settings["schedule_logs"] = logs
        return settings
    max_items = int(task.get("max_items") or 5)
    min_duration_seconds = int(task.get("min_duration_seconds") or 0)
    only_streams = bool(task.get("only_streams") or False)
    run_id = str(uuid.uuid4())
    run_start = _now()
    run_entry = {
        "id": run_id,
        "task_id": task.get("id"),
        "channel_id": task.get("channel_id"),
        "channel_name": task.get("channel_name"),
        "schedule_label": _format_schedule_label(task),
        "triggered_at": _iso(run_start),
        "finished_at": "",
        "status": "running",
        "total_found": 0,
        "new_items": 0,
        "success_items": 0,
        "failed_items": 0,
        "duration_seconds": 0,
        "model": summary_model_name,
        "fact_check_model": fact_check_model_name,
        "error": "",
    }
    try:
        videos = get_channel_recent_videos(
            channel_url,
            limit=max_items,
            proxy_url=eff_proxy,
            timeout_seconds=timeout_seconds,
            filter_longest=True,
            min_duration_seconds=min_duration_seconds,
            only_streams=only_streams
        )
        run_entry["total_found"] = len(videos)
        for v in videos:
            vid = v.get("id")
            if not vid or vid in processed_set:
                continue
            run_entry["new_items"] += 1
            item_record = {
                "run_id": run_id,
                "video_id": vid,
                "title": v.get("title"),
                "url": v.get("url"),
                "channel_name": task.get("channel_name") or "",
                "platform": task.get("platform") or "",
                "status": "running",
                "summary": "",
                "error": "",
                "created_at": _iso(_now()),
                "duration_seconds": 0,
            }
            item_start = _now()
            text, err = internal_fetch_transcript(v.get("url"))
            if err:
                item_record["status"] = "failed"
                item_record["error"] = err
                item_record["duration_seconds"] = int((_now() - item_start).total_seconds())
                run_entry["failed_items"] += 1
                run_items.append(item_record)
                continue
            if not api_key:
                item_record["status"] = "failed"
                item_record["error"] = "缺少 API Key，无法生成总结"
                item_record["duration_seconds"] = int((_now() - item_start).total_seconds())
                run_entry["failed_items"] += 1
                run_items.append(item_record)
                continue
            try:
                summary = summarize_text(
                    text,
                    api_key,
                    base_url,
                    summary_model_name,
                    eff_proxy,
                    fact_check_model=fact_check_model_name,
                )
                item_record["status"] = "success"
                item_record["summary"] = summary
                item_record["duration_seconds"] = int((_now() - item_start).total_seconds())
                run_entry["success_items"] += 1
                processed_set.add(vid)
                
                # 自动保存到历史记录
                try:
                    add_history_entry("schedule", v.get("url"), summary, text)
                except Exception as e_hist:
                    print(f"Failed to save history (schedule): {e_hist}")
                    
            except Exception as e:
                item_record["status"] = "failed"
                item_record["error"] = str(e)
                item_record["duration_seconds"] = int((_now() - item_start).total_seconds())
                run_entry["failed_items"] += 1
            run_items.append(item_record)
            time.sleep(0.3)
        if run_entry["new_items"] == 0:
            run_entry["status"] = "no_update"
        elif run_entry["failed_items"] == 0:
            run_entry["status"] = "success"
        elif run_entry["success_items"] == 0:
            run_entry["status"] = "failed"
        else:
            run_entry["status"] = "partial"
        _append_log(logs, "info", f"任务执行完成，新增 {run_entry.get('new_items') or 0} 个视频", task.get("id"))
        task["last_error"] = ""
        task["retry_count"] = 0
        task["next_retry_at"] = ""
        task["last_run_at"] = _iso(_now())
        task["next_run_at"] = _iso(_compute_next_run(task, _now()) or "")
    except Exception as e:
        task["last_error"] = str(e)
        retry_count = int(task.get("retry_count") or 0) + 1
        task["retry_count"] = retry_count
        if retry_count <= 3:
            next_retry = _now() + timedelta(minutes=5)
            task["next_retry_at"] = _iso(next_retry)
            _append_log(logs, "warning", f"任务失败，将在 5 分钟后重试({retry_count}/3)：{e}", task.get("id"))
        else:
            task["next_retry_at"] = ""
            _append_log(logs, "error", f"任务失败并超过最大重试次数：{e}", task.get("id"))
        run_entry["status"] = "failed"
        run_entry["error"] = str(e)
    run_entry["finished_at"] = _iso(_now())
    run_entry["duration_seconds"] = int((_now() - run_start).total_seconds())
    runs.append(run_entry)
    runs, run_items = _trim_schedule_records(runs, run_items)
    settings["schedule_logs"] = logs[-200:]
    settings["scheduled_runs"] = runs
    settings["scheduled_run_items"] = run_items
    settings["scheduled_processed_ids"] = list(processed_set)
    return settings

# --- 辅助函数 ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def load_subscriptions():
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_subscriptions(subs):
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

@st.cache_resource
def _start_scheduler_thread():
    # 使用 cache_resource 确保全局只启动一个调度线程
    def _loop():
        while True:
            try:
                settings, tasks, logs, runs, run_items, processed_ids = _load_scheduled_state()
                now = _now()
                due_tasks = []
                for t in tasks:
                    if not t.get("enabled"):
                        continue
                    next_retry = _parse_iso(t.get("next_retry_at"))
                    next_run = _parse_iso(t.get("next_run_at"))
                    if next_retry and next_retry <= now:
                        due_tasks.append(t)
                        continue
                    if not next_run:
                        computed = _compute_next_run(t, now)
                        t["next_run_at"] = _iso(computed) if computed else ""
                        continue
                    if next_run <= now:
                        due_tasks.append(t)
                if due_tasks:
                    for t in due_tasks:
                        settings = _run_task_once(t, settings)
                runs = settings.get("scheduled_runs") or runs
                run_items = settings.get("scheduled_run_items") or run_items
                processed_ids = settings.get("scheduled_processed_ids") or processed_ids
                _save_scheduled_state(settings, tasks, settings.get("schedule_logs") or [], runs, run_items, processed_ids)
            except Exception as e:
                # print(f"Scheduler error: {e}")
                pass
            time.sleep(15)
    
    worker = threading.Thread(target=_loop, daemon=True)
    worker.start()
    return worker

def _start_scheduler_once():
    # 只需要调用 cache_resource 装饰的函数
    _start_scheduler_thread()

def _format_countdown(target_time):
    if not target_time:
        return "—"
    now = _now()
    delta = target_time - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "即将执行"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    parts.append(f"{minutes}分")
    return "".join(parts)

def _format_schedule_label(task):
    schedule_type = (task.get("schedule_type") or "").lower()
    if schedule_type == "daily":
        return f"每天 {task.get('time')}"
    if schedule_type == "weekly":
        weekdays = task.get("weekdays") or []
        labels = ["周一","周二","周三","周四","周五","周六","周日"]
        day_text = "、".join([labels[i] for i in weekdays if isinstance(i, int) and 0 <= i <= 6])
        return f"{day_text} {task.get('time')}"
    if schedule_type == "interval":
        return f"每 {task.get('interval_hours')} 小时"
    if schedule_type == "cron":
        return f"Cron: {task.get('cron')}"
    return "未设置"

def _build_month_calendar(tasks):
    now = _now()
    year = now.year
    month = now.month
    cal = calendar.monthcalendar(year, month)
    task_days = {}
    for t in tasks:
        next_time = _parse_iso(t.get("next_run_at")) or _parse_iso(t.get("next_retry_at"))
        if next_time and next_time.year == year and next_time.month == month:
            task_days.setdefault(next_time.day, 0)
            task_days[next_time.day] += 1
    rows = []
    header = ["一", "二", "三", "四", "五", "六", "日"]
    rows.append("|" + "|".join(header) + "|")
    rows.append("|" + "|".join(["---"] * 7) + "|")
    for week in cal:
        cells = []
        for day in week:
            if day == 0:
                cells.append(" ")
            else:
                count = task_days.get(day, 0)
                if count > 0:
                    cells.append(f"{day} 🔔{count}")
                else:
                    cells.append(str(day))
        rows.append("|" + "|".join(cells) + "|")
    return "\n".join(rows)

# --- 页面配置 ---
st.set_page_config(
    page_title="YouTube Summarizer",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        max-width: 1400px;
    }
    div[data-testid="stMarkdownContainer"],
    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li,
    div[data-testid="stMarkdownContainer"] a,
    div[data-testid="stMarkdownContainer"] code {
        overflow-wrap: anywhere;
        word-break: break-word;
        white-space: normal;
    }
    div[data-testid="stTabs"] button[role="tab"] {
        white-space: normal;
    }
    div[data-testid="stFileUploader"] > label {
        display: none;
    }
    div[data-testid="stFileUploaderDropzone"] {
        padding: 0.9rem 1rem;
    }
    div[data-testid="stFileUploaderDropzone"] > div {
        flex-wrap: wrap;
        row-gap: 0.6rem;
    }
    div[data-testid="stFileUploaderDropzoneInstructions"] {
        min-width: 0;
        flex: 1 1 260px;
    }
    div[data-testid="stFileUploaderDropzone"] button {
        white-space: nowrap;
    }
    @media (max-width: 900px) {
        .block-container {
            padding-left: 0.85rem;
            padding-right: 0.85rem;
        }
        div[data-testid="stFileUploaderDropzone"] > div {
            flex-direction: column;
            align-items: stretch;
        }
        div[data-testid="stFileUploaderDropzone"] button {
            width: 100%;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Session State 初始化 ---
if "settings" not in st.session_state:
    st.session_state.settings = load_settings()

if "subscriptions" not in st.session_state:
    st.session_state.subscriptions = load_subscriptions()
if "updates" not in st.session_state:
    st.session_state.updates = {} # {channel_id: [video_list]}

if "remember_api_key" not in st.session_state:
    st.session_state.remember_api_key = bool(st.session_state.settings.get("remember_api_key", True))
if "api_key" not in st.session_state:
    if st.session_state.remember_api_key:
        st.session_state.api_key = st.session_state.settings.get("api_key", "")
    else:
        st.session_state.api_key = ""
if "base_url" not in st.session_state:
    st.session_state.base_url = st.session_state.settings.get("base_url", "https://api.openai.com/v1")
if "model" not in st.session_state:
    st.session_state.model = st.session_state.settings.get("model", "gpt-3.5-turbo")
if "summary_model" not in st.session_state:
    st.session_state.summary_model = str(st.session_state.settings.get("summary_model") or "").strip()
if "fact_check_model" not in st.session_state:
    st.session_state.fact_check_model = str(st.session_state.settings.get("fact_check_model") or "").strip()
if "proxy" not in st.session_state:
    st.session_state.proxy = st.session_state.settings.get("proxy", "")
if "transcript_text" not in st.session_state:
    st.session_state.transcript_text = ""
if "summary_text" not in st.session_state:
    st.session_state.summary_text = ""
if "manual_transcript_text" not in st.session_state:
    st.session_state.manual_transcript_text = ""
if "manual_source_url" not in st.session_state:
    st.session_state.manual_source_url = ""
if "manual_summary_text" not in st.session_state:
    st.session_state.manual_summary_text = ""
if "manual_summary_duration" not in st.session_state:
    st.session_state.manual_summary_duration = {}
if "manual_bridge_meta" not in st.session_state:
    st.session_state.manual_bridge_meta = {}
if "manual_auto_payload_id" not in st.session_state:
    st.session_state.manual_auto_payload_id = ""
if "manual_last_payload_id" not in st.session_state:
    st.session_state.manual_last_payload_id = ""
if "video_extension_payload_id" not in st.session_state:
    st.session_state.video_extension_payload_id = ""
if "video_extension_last_payload_id" not in st.session_state:
    st.session_state.video_extension_last_payload_id = ""
if "video_extension_request_result" not in st.session_state:
    st.session_state.video_extension_request_result = None
if "video_extension_request_debug_text" not in st.session_state:
    st.session_state.video_extension_request_debug_text = ""
if "video_extension_request_pending" not in st.session_state:
    st.session_state.video_extension_request_pending = False
if "video_extension_request_url" not in st.session_state:
    st.session_state.video_extension_request_url = ""
if "video_extension_request_id" not in st.session_state:
    st.session_state.video_extension_request_id = ""
if "video_extension_request_component_key" not in st.session_state:
    st.session_state.video_extension_request_component_key = ""
if "current_video_url" not in st.session_state:
    st.session_state.current_video_url = ""
if "video_extension_auto_summary_pending" not in st.session_state:
    st.session_state.video_extension_auto_summary_pending = False
if "video_extension_auto_summary_url" not in st.session_state:
    st.session_state.video_extension_auto_summary_url = ""
if "video_extension_auto_summary_fetch_duration" not in st.session_state:
    st.session_state.video_extension_auto_summary_fetch_duration = 0.0
if "video_fact_check_task_id" not in st.session_state:
    st.session_state.video_fact_check_task_id = ""
if "video_fact_check_status" not in st.session_state:
    st.session_state.video_fact_check_status = "idle"
if "video_fact_check_error" not in st.session_state:
    st.session_state.video_fact_check_error = ""
if "video_fact_check_url" not in st.session_state:
    st.session_state.video_fact_check_url = ""
if "video_fact_check_applied_task_id" not in st.session_state:
    st.session_state.video_fact_check_applied_task_id = ""
if "video_fact_check_note" not in st.session_state:
    st.session_state.video_fact_check_note = ""
if "prefer_paste_tab" not in st.session_state:
    st.session_state.prefer_paste_tab = False
if "document_raw_text" not in st.session_state:
    st.session_state.document_raw_text = ""
if "document_clean_text" not in st.session_state:
    st.session_state.document_clean_text = ""
if "document_summary_text" not in st.session_state:
    st.session_state.document_summary_text = ""
if "document_fact_check_text" not in st.session_state:
    st.session_state.document_fact_check_text = ""
if "document_meta" not in st.session_state:
    st.session_state.document_meta = {}
if "document_source_url" not in st.session_state:
    st.session_state.document_source_url = ""
if "document_results" not in st.session_state:
    st.session_state.document_results = {
        "upload": {},
        "url": {},
    }
if "whisper_device_tag" not in st.session_state:
    st.session_state.whisper_device_tag = ""
if "asr_force_cpu" not in st.session_state:
    st.session_state.asr_force_cpu = False
if "available_models" not in st.session_state:
    st.session_state.available_models = [
        "gpt-3.5-turbo",
        "gpt-4o",
        "gpt-4-turbo",
        "deepseek-chat",
        "deepseek-reasoner",
        "qwen-plus",
        "qwen-turbo",
        "moonshot-v1-8k",
    ]
if "search_results" not in st.session_state:
    st.session_state.search_results = None
if "last_saved_settings" not in st.session_state:
    remember_api_key_initial = bool(st.session_state.remember_api_key)
    st.session_state.last_saved_settings = {
        "api_key": st.session_state.settings.get("api_key", "") if remember_api_key_initial else "",
        "base_url": st.session_state.settings.get("base_url", "https://api.openai.com/v1"),
        "model": st.session_state.settings.get("model", "gpt-3.5-turbo"),
        "summary_model": str(st.session_state.settings.get("summary_model") or "").strip(),
        "fact_check_model": str(st.session_state.settings.get("fact_check_model") or "").strip(),
        "proxy": st.session_state.settings.get("proxy", ""),
        "remember_api_key": remember_api_key_initial,
    }

def reset_video_fact_check_state() -> None:
    st.session_state.video_fact_check_task_id = ""
    st.session_state.video_fact_check_status = "idle"
    st.session_state.video_fact_check_error = ""
    st.session_state.video_fact_check_url = ""
    st.session_state.video_fact_check_applied_task_id = ""
    st.session_state.video_fact_check_note = ""


def _is_supported_video_source_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    if not value:
        return False
    return any(
        marker in value
        for marker in (
            "youtube.com/watch",
            "youtube.com/shorts/",
            "youtube.com/live/",
            "youtu.be/",
            "bilibili.com/video/",
            "b23.tv/",
        )
    )

# --- 后台硬编码/环境变量配置 (对外隐藏设置) ---
proxy_input = os.environ.get("PROXY_URL", st.session_state.settings.get("proxy", ""))
use_system_proxy = False
languages = "zh-Hans,zh-Hant,zh-TW,zh,en,ja,ko"
cookies_file = os.environ.get("YTDLP_COOKIES_FILE", "").strip()
cookies_content = os.environ.get("YTDLP_COOKIES_CONTENT", "")
cookies_content_b64 = os.environ.get("YTDLP_COOKIES_CONTENT_B64", "").strip()
cookies_browser = os.environ.get("YTDLP_COOKIES_BROWSER", "").strip().lower()
auto_cookies = bool(cookies_browser)
timeout = 60
retries = 3

asr_enabled = False
asr_model = os.environ.get("ASR_MODEL", "base")
asr_fast_mode = True

api_key = os.environ.get("OPENAI_API_KEY", st.session_state.settings.get("api_key", ""))
base_url = os.environ.get("OPENAI_BASE_URL", st.session_state.settings.get("base_url", "https://api.openai.com/v1"))
summary_model_selected, fact_check_model_selected = resolve_pipeline_models(
    st.session_state.settings,
    env=os.environ,
    base_url_value=base_url,
)
model_selected = summary_model_selected
pipeline_model_label = format_pipeline_model_label(summary_model_selected, fact_check_model_selected)

st.session_state.proxy = proxy_input
st.session_state.api_key = api_key
st.session_state.base_url = base_url
st.session_state.model = model_selected
st.session_state.summary_model = summary_model_selected
st.session_state.fact_check_model = fact_check_model_selected

query_params = st.query_params
ext_payload_id = str(query_params.get("ext_payload_id", "") or "").strip()
ext_source_url = str(query_params.get("ext_source_url", "") or "").strip()
ext_transcript = str(query_params.get("ext_transcript", "") or "").strip()
ext_autosubmit = str(query_params.get("ext_autosubmit", "") or "").strip().lower() in {"1", "true", "yes"}
bridge_payload_waiting = False
bridge_payload_error = ""

if ext_source_url and not st.session_state.manual_source_url:
    st.session_state.manual_source_url = ext_source_url
    st.session_state.prefer_paste_tab = True

if ext_payload_id and st.session_state.manual_last_payload_id != ext_payload_id:
    # 新一轮扩展导入开始时先清掉上一轮 bridge 元信息，避免残留“本地节点/兜底”说明。
    st.session_state.manual_bridge_meta = {}

if ext_payload_id and st.session_state.manual_last_payload_id != ext_payload_id and not ext_transcript:
    bridge_payload, bridge_payload_error = wait_for_extension_bridge_payload(ext_payload_id)
    if not bridge_payload and bridge_payload_error != "payload_not_found":
        bridge_payload = read_extension_bridge_payload(ext_payload_id, consume=True)
    normalized_bridge_payload = normalize_extension_bridge_payload(bridge_payload)
    bridge_transcript = str(normalized_bridge_payload.get("transcript_text") or "").strip()
    if bridge_transcript:
        ext_transcript = bridge_transcript
        ext_source_url = str(normalized_bridge_payload.get("source_url") or ext_source_url).strip()
        st.session_state.manual_bridge_meta = {
            "payload_id": str(normalized_bridge_payload.get("payload_id") or ext_payload_id).strip(),
            "bridge_version": int(normalized_bridge_payload.get("bridge_version") or 1),
            "request_id": str(normalized_bridge_payload.get("request_id") or "").strip(),
            "source_kind": str(normalized_bridge_payload.get("source_kind") or "").strip(),
            "source_type": str(normalized_bridge_payload.get("source_type") or "").strip(),
            "fallback_used": bool(normalized_bridge_payload.get("fallback_used")),
            "text_source_reason": str(normalized_bridge_payload.get("text_source_reason") or "").strip(),
            "title": str(normalized_bridge_payload.get("title") or "").strip(),
        }
    else:
        bridge_payload_waiting = True

if ext_payload_id and ext_transcript and st.session_state.manual_last_payload_id != ext_payload_id:
    st.session_state.manual_source_url = ext_source_url
    st.session_state.manual_transcript_text = ext_transcript
    st.session_state.manual_summary_text = ""
    st.session_state.manual_summary_duration = {}
    route_extension_payload_to_video = ext_autosubmit and _is_supported_video_source_url(ext_source_url)
    st.session_state.prefer_paste_tab = not route_extension_payload_to_video
    if not st.session_state.manual_bridge_meta:
        # 兼容 bridge 元信息未及时返回的情况，至少明确这是扩展直提文本。
        st.session_state.manual_bridge_meta = {
            "payload_id": ext_payload_id,
            "bridge_version": 2,
            "request_id": "",
            "source_kind": "extension",
            "source_type": "subtitle",
            "fallback_used": False,
            "text_source_reason": "extension_direct_extract",
            "title": "",
        }
    if route_extension_payload_to_video:
        st.session_state.transcript_text = ext_transcript
        st.session_state.summary_text = ""
        st.session_state.whisper_device_tag = ""
        reset_video_fact_check_state()
        st.session_state.current_video_url = ext_source_url
        st.session_state.input_url = ext_source_url
        st.session_state.video_extension_auto_summary_pending = True
        st.session_state.video_extension_auto_summary_url = ext_source_url
        st.session_state.video_extension_auto_summary_fetch_duration = 0.0
        st.session_state.manual_last_payload_id = ext_payload_id
        st.session_state.manual_auto_payload_id = ""
        try:
            st.query_params.clear()
        except Exception:
            pass
    elif ext_autosubmit:
        st.session_state.manual_auto_payload_id = ext_payload_id

video_extension_payload_id = st.session_state.get("video_extension_payload_id") or ""
video_extension_last_payload_id = st.session_state.get("video_extension_last_payload_id") or ""
if video_extension_payload_id and video_extension_payload_id != video_extension_last_payload_id:
    video_bridge_payload, video_bridge_payload_error = wait_for_extension_bridge_payload(video_extension_payload_id)
    if not video_bridge_payload and video_bridge_payload_error != "payload_not_found":
        video_bridge_payload = read_extension_bridge_payload(video_extension_payload_id, consume=True)
    normalized_video_bridge_payload = normalize_extension_bridge_payload(video_bridge_payload)
    video_bridge_transcript = str(normalized_video_bridge_payload.get("transcript_text") or "").strip()
    if video_bridge_transcript:
        st.session_state.video_fact_check_task_id = ""
        st.session_state.video_fact_check_status = "idle"
        st.session_state.video_fact_check_error = ""
        st.session_state.video_fact_check_url = ""
        st.session_state.video_fact_check_applied_task_id = ""
        st.session_state.video_fact_check_note = ""
        print(
            "VideoBridgePayloadReceived: "
            f"payload_id={str(normalized_video_bridge_payload.get('payload_id') or video_extension_payload_id).strip()}, "
            f"request_id={str(normalized_video_bridge_payload.get('request_id') or '').strip()}, "
            f"source_url={str(normalized_video_bridge_payload.get('source_url') or '').strip()}, "
            f"transcript_len={len(video_bridge_transcript)}, "
            f"source_type={str(normalized_video_bridge_payload.get('source_type') or '').strip()}, "
            f"text_source_reason={str(normalized_video_bridge_payload.get('text_source_reason') or '').strip()}"
        , flush=True)
        st.session_state.transcript_text = video_bridge_transcript
        st.session_state.summary_text = ""
        st.session_state.whisper_device_tag = ""
        st.session_state.manual_bridge_meta = {
            "payload_id": str(normalized_video_bridge_payload.get("payload_id") or video_extension_payload_id).strip(),
            "bridge_version": int(normalized_video_bridge_payload.get("bridge_version") or 1),
            "request_id": str(normalized_video_bridge_payload.get("request_id") or "").strip(),
            "source_kind": str(normalized_video_bridge_payload.get("source_kind") or "extension").strip(),
            "source_type": str(normalized_video_bridge_payload.get("source_type") or "subtitle").strip(),
            "fallback_used": bool(normalized_video_bridge_payload.get("fallback_used")),
            "text_source_reason": str(normalized_video_bridge_payload.get("text_source_reason") or "extension_extract_by_url").strip(),
            "title": str(normalized_video_bridge_payload.get("title") or "").strip(),
        }
        st.session_state.video_extension_last_payload_id = video_extension_payload_id
        st.session_state.video_extension_auto_summary_pending = True
        st.session_state.video_extension_auto_summary_url = str(
            normalized_video_bridge_payload.get("source_url")
            or st.session_state.get("current_video_url")
            or st.session_state.get("input_url")
            or ""
        ).strip()
        st.session_state.video_extension_auto_summary_fetch_duration = 0.0



# --- 主界面 ---
st.title("🎬 Video Summarizer")
st.caption("本地运行的视频字幕抓取与 AI 总结工具 | 支持 YouTube & Bilibili | 插件优先字幕提取")

# 一级导航：按用户任务而不是输入形态组织页面。
tab_processing, tab_tasks, tab_automation, tab_library, tab_settings = st.tabs([
    "🧭 处理中心",
    "📋 任务中心",
    "📡 订阅自动化",
    "🗂️ 内容资产库",
    "🛠️ 设置与诊断",
])

# --- 通用逻辑函数 (供两个 Tab 使用) ---
def internal_fetch_transcript(video_url, progress_callback=None):
    """
    核心抓取逻辑，返回 (transcript_text, error_msg)
    """
    try:
        def is_html_like_text(text: str) -> bool:
            if not text:
                return False
            sample = text.strip().lower()
            if sample.startswith("<!doctype") or sample.startswith("<html"):
                return True
            if "<html" in sample[:2000]:
                return True
            if "<head" in sample and "<body" in sample:
                return True
            return False

        if progress_callback: progress_callback(10, "解析视频信息...")
        video_id, v_url, languages_effective = get_transcript_from_input(video_url, languages)
        
        api = build_api(
            proxy_url=proxy_input,
            timeout_seconds=float(timeout),
            use_system_proxy=use_system_proxy,
            retries=int(retries),
        )
        # 注入私有属性；当前页面已临时关闭音频下载/Whisper 转写兜底
        setattr(api, "_cookies_file", cookies_file)
        setattr(api, "_cookies_content", cookies_content)
        setattr(api, "_cookies_content_b64", cookies_content_b64)
        setattr(api, "_cookies_from_browser", cookies_browser if auto_cookies else "")
        setattr(api, "_asr_enabled", asr_enabled)
        setattr(api, "_asr_model", asr_model) # 传递用户选择的 model
        setattr(api, "_asr_language", "auto")
        setattr(api, "_asr_fast_mode", asr_fast_mode)
        setattr(api, "_asr_force_cpu", st.session_state.asr_force_cpu)
        
        # 定义一个内部回调，用于将底层状态透传给 UI
        def status_relay(msg):
            if progress_callback:
                progress_callback(50, f"{msg}")

        setattr(api, "_status_callback", status_relay)
        
        langs_list = [s.strip() for s in languages_effective.split(",") if s.strip()]
        
        if progress_callback:
            progress_callback(30, "获取字幕文本...")
        # 记录开始时间
        import time
        t0 = time.time()
        
        text = get_video_transcript(api, video_id, video_url=v_url, languages=langs_list)
        if is_html_like_text(text):
            return None, "检测到返回内容为 HTML 页面源码，无法用于总结。请确认视频可访问，或更换网络/代理后重试。"
        
        t1 = time.time()
        elapsed = t1 - t0
        
        if progress_callback: progress_callback(100, f"抓取完成！耗时: {elapsed:.1f}s")
        return text, None
    except Exception as e:
        return None, format_error(e)

def internal_summarize(
    text,
    summary_model_name,
    fact_check_model_name=None,
    api_key_override=None,
    base_url_override=None,
    proxy_override=None,
    enable_fact_check=True,
):
        """
        核心总结逻辑，返回 (summary_text, error_msg)
        支持外部传入凭证（用于后台线程）
        """
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = proxy_override or proxy_input
        
        if not eff_api_key:
            return None, "请在侧边栏填写 API Key"
        try:
            print(
                "InternalSummarize: "
                f"text_len={len(str(text or ''))}, "
                f"summary_model={summary_model_name}, "
                f"fact_check_model={fact_check_model_name}, "
                f"enable_fact_check={bool(enable_fact_check)}"
            , flush=True)
            summary = summarize_text(
                text,
                eff_api_key,
                eff_base_url,
                summary_model_name,
                eff_proxy,
                fact_check_model=fact_check_model_name,
                enable_fact_check=enable_fact_check,
                stream=False  # 后台任务默认不使用流式
            )
            return summary, None
        except Exception as e:
            return None, str(e)


def _build_summary_json(summary_markdown: str, fact_check_markdown: str = "") -> str:
    return json.dumps(
        {
            "summary_markdown": str(summary_markdown or "").strip(),
            "fact_check_markdown": str(fact_check_markdown or "").strip(),
        },
        ensure_ascii=False,
    )


def _merge_fact_check_into_summary(summary_content: str, fact_check_markdown: str) -> str:
    summary_md, _existing_fact_md = _parse_summary_for_ui(summary_content)
    if not summary_md:
        summary_md = str(summary_content or "").strip()
    return _build_summary_json(summary_md, fact_check_markdown)


def _build_video_fact_check_cache_key(url: str, summary_markdown: str, transcript_text: str) -> str:
    raw = "\n".join(
        [
            str(url or "").strip(),
            str(summary_markdown or "").strip()[:2500],
            str(transcript_text or "").strip()[:5000],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def start_video_fact_check_async(url: str, transcript_text: str, summary_content: str) -> None:
    summary_md, _fact_md = _parse_summary_for_ui(summary_content)
    transcript_value = str(transcript_text or "").strip()
    url_value = str(url or "").strip()
    if not summary_md or not transcript_value or not api_key:
        reset_video_fact_check_state()
        return

    runtime = _get_video_fact_check_runtime()
    plan = decide_video_fact_check_plan(transcript_value, summary_md)
    if not bool(plan.get("should_fact_check")):
        reset_video_fact_check_state()
        st.session_state.video_fact_check_status = "skipped"
        st.session_state.video_fact_check_note = str(plan.get("reason") or "").strip()
        st.session_state.video_fact_check_url = url_value
        return

    max_claims = int(plan.get("recommended_claim_count") or 3)
    if max_claims not in {3, 5}:
        max_claims = 3
    cache_key = _build_video_fact_check_cache_key(url_value, summary_md, transcript_value)

    with runtime["lock"]:
        cached_result = str((runtime.get("result_cache") or {}).get(cache_key) or "").strip()
    if cached_result:
        st.session_state.summary_text = _merge_fact_check_into_summary(summary_content, cached_result)
        st.session_state.video_fact_check_task_id = f"video_fact_check_cache_{cache_key[:12]}"
        st.session_state.video_fact_check_status = "success"
        st.session_state.video_fact_check_error = ""
        st.session_state.video_fact_check_url = url_value
        st.session_state.video_fact_check_applied_task_id = st.session_state.video_fact_check_task_id
        st.session_state.video_fact_check_note = "新闻核查已命中缓存。"
        return

    task_id = f"video_fact_check_{uuid.uuid4().hex}"

    with runtime["lock"]:
        runtime["tasks"][task_id] = {
            "status": "queued",
            "result": "",
            "error": "",
            "url": url_value,
            "cache_key": cache_key,
            "note": str(plan.get("reason") or "").strip(),
        }

    st.session_state.video_fact_check_task_id = task_id
    st.session_state.video_fact_check_status = "queued"
    st.session_state.video_fact_check_error = ""
    st.session_state.video_fact_check_url = url_value
    st.session_state.video_fact_check_applied_task_id = ""
    st.session_state.video_fact_check_note = str(plan.get("reason") or "").strip()

    eff_api_key = api_key
    eff_base_url = base_url
    eff_proxy = proxy_input
    eff_fact_model = fact_check_model_selected

    def _worker():
        with runtime["lock"]:
            task = runtime["tasks"].get(task_id) or {}
            task["status"] = "running"
            runtime["tasks"][task_id] = task
        try:
            fact_markdown = fact_check_document_claims(
                text=transcript_value,
                summary_markdown=summary_md,
                api_key=eff_api_key,
                base_url=eff_base_url,
                model=eff_fact_model,
                proxy_url=eff_proxy,
                max_claims=max_claims,
            )
            with runtime["lock"]:
                result_cache = runtime.setdefault("result_cache", {})
                result_cache[cache_key] = str(fact_markdown or "").strip()
                if len(result_cache) > 80:
                    oldest_key = next(iter(result_cache))
                    if oldest_key != cache_key:
                        result_cache.pop(oldest_key, None)
                runtime["tasks"][task_id] = {
                    "status": "success",
                    "result": str(fact_markdown or "").strip(),
                    "error": "",
                    "url": url_value,
                    "cache_key": cache_key,
                    "note": str(plan.get("reason") or "").strip(),
                }
        except Exception as exc:
            with runtime["lock"]:
                runtime["tasks"][task_id] = {
                    "status": "error",
                    "result": "",
                    "error": str(exc),
                    "url": url_value,
                    "cache_key": cache_key,
                    "note": str(plan.get("reason") or "").strip(),
                }

    threading.Thread(target=_worker, daemon=True).start()


def sync_video_fact_check_state() -> None:
    task_id = str(st.session_state.get("video_fact_check_task_id") or "").strip()
    if not task_id:
        return

    runtime = _get_video_fact_check_runtime()
    with runtime["lock"]:
        task = dict(runtime["tasks"].get(task_id) or {})

    if not task:
        return

    status = str(task.get("status") or "idle").strip()
    st.session_state.video_fact_check_status = status
    st.session_state.video_fact_check_error = str(task.get("error") or "").strip()
    st.session_state.video_fact_check_url = str(task.get("url") or st.session_state.get("video_fact_check_url") or "").strip()
    st.session_state.video_fact_check_note = str(task.get("note") or st.session_state.get("video_fact_check_note") or "").strip()

    if (
        status == "success"
        and st.session_state.get("video_fact_check_applied_task_id") != task_id
        and str(task.get("result") or "").strip()
        and st.session_state.summary_text
    ):
        st.session_state.summary_text = _merge_fact_check_into_summary(
            st.session_state.summary_text,
            str(task.get("result") or "").strip(),
        )
        st.session_state.video_fact_check_applied_task_id = task_id
        st.session_state.video_fact_check_status = "success"

def run_document_summary_pipeline(
    extracted,
    summary_model_name,
    fact_check_model_name,
    eff_api_key,
    eff_base_url,
    eff_proxy,
    progress_callback=None,
):
        """
        复用文档总结主流程，统一执行正文总结、文档判定与关键声明事实核查。
        """
        def relay_document_progress(pct, message):
            if progress_callback:
                progress_callback(25 + int(min(max(pct, 0), 100) * 0.45), message)

        summary_result = summarize_document_text(
            extracted["clean_text"],
            eff_api_key,
            eff_base_url,
            summary_model_name,
            eff_proxy,
            progress_callback=relay_document_progress,
        )
        if progress_callback:
            progress_callback(72, "正在判断文档类型与是否需要事实核查...")

        fact_check_plan = classify_document_for_fact_check(
            text=extracted["clean_text"],
            summary_markdown=summary_result["summary_markdown"],
            api_key=eff_api_key,
            base_url=eff_base_url,
            model=fact_check_model_name,
            proxy_url=eff_proxy,
        )

        fact_check_markdown = ""
        if bool(fact_check_plan.get("should_fact_check")):
            def relay_fact_progress(pct, message):
                if progress_callback:
                    progress_callback(72 + int(min(max(pct, 0), 100) * 0.28), message)

            fact_check_markdown = fact_check_document_claims(
                text=extracted["clean_text"],
                summary_markdown=summary_result["summary_markdown"],
                api_key=eff_api_key,
                base_url=eff_base_url,
                model=fact_check_model_name,
                proxy_url=eff_proxy,
                max_claims=int(fact_check_plan.get("recommended_claim_count") or 5),
                progress_callback=relay_fact_progress,
            )

        return {
            "extract": extracted,
            "summary": summary_result,
            "fact_check_markdown": fact_check_markdown,
            "fact_check_plan": fact_check_plan,
        }


def internal_summarize_document(file_name, file_bytes, model_name, progress_callback=None, api_key_override=None, base_url_override=None, proxy_override=None):
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = proxy_override or proxy_input
        summary_model_name = str(model_name or summary_model_selected).strip() or summary_model_selected
        fact_check_model_name = fact_check_model_selected

        ok, err = validate_document_upload(file_name, len(file_bytes))
        if not ok:
            return None, err
        if not eff_api_key:
            return None, "请先填写 API Key。"

        if progress_callback:
            progress_callback(10, "正在解析文档...")
        extracted = extract_document_text(file_bytes, file_name)

        if progress_callback:
            progress_callback(25, f"文档解析完成，正文约 {extracted['char_count']} 字符。")
        return run_document_summary_pipeline(
            extracted,
            summary_model_name,
            fact_check_model_name,
            eff_api_key,
            eff_base_url,
            eff_proxy,
            progress_callback=progress_callback,
        ), None


def internal_summarize_document_url(source_url, model_name, progress_callback=None, api_key_override=None, base_url_override=None, proxy_override=None):
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = proxy_override or proxy_input
        summary_model_name = str(model_name or summary_model_selected).strip() or summary_model_selected
        fact_check_model_name = fact_check_model_selected

        if not eff_api_key:
            return None, "请先填写 API Key。"
        if progress_callback:
            progress_callback(10, "正在抓取在线文档/网页...")

        extracted = extract_document_from_url(source_url, proxy_url=eff_proxy)
        if progress_callback:
            progress_callback(25, f"在线内容解析完成，正文约 {extracted['char_count']} 字符。")
        return run_document_summary_pipeline(
            extracted,
            summary_model_name,
            fact_check_model_name,
            eff_api_key,
            eff_base_url,
            eff_proxy,
            progress_callback=progress_callback,
        ), None


# ==========================
# ====== 新增：后台任务状态轮询 ======
# ==========================
import time
from task_runner import submit_task, get_task_status

if "bg_task_id" not in st.session_state:
    st.session_state.bg_task_id = None

def render_background_task_status_panel():
    """
    渲染后台任务状态轮询区，并返回当前任务 ID 与状态信息。
    """
    current_bg_task_id = st.session_state.bg_task_id or ""
    current_bg_task_status = None

    if st.session_state.bg_task_id:
        task_id = st.session_state.bg_task_id
        status_info = get_task_status(task_id)
        current_bg_task_status = status_info

        st.info(f"⏳ 后台任务进行中... (ID: {task_id[:8]})")
        status_col1, status_col2 = st.columns([3, 1])

        with status_col1:
            if status_info["status"] == "queued":
                st.warning("🔄 任务排队中...")
            elif status_info["status"] == "running":
                with st.spinner("🚀 正在抓取和总结中，请稍候..."):
                    time.sleep(2)
            elif status_info["status"] == "success":
                st.success("✅ 任务完成！")
                st.markdown("### 总结结果")
                st.write(status_info.get("result", "无内容返回"))
                if st.button("清理状态并开启新任务", key="bg_task_clear_success"):
                    st.session_state.bg_task_id = None
                    st.rerun()
            elif status_info["status"] == "failed":
                st.error(f"❌ 任务失败: {status_info.get('error', '未知错误')}")
                if st.button("清理状态并重试", key="bg_task_clear_failed"):
                    st.session_state.bg_task_id = None
                    st.rerun()

        with status_col2:
            if status_info["status"] in ["queued", "running"]:
                if st.button("刷新进度", key="bg_task_refresh_progress"):
                    st.rerun()

        if status_info["status"] in ["queued", "running"]:
            time.sleep(3)
            st.rerun()

    return current_bg_task_id, current_bg_task_status
# ====== 新增结束 ======

def render_task_center_metrics(task_status_value, task_defs, task_run_items):
    """
    渲染任务中心顶部指标栏。
    """
    failed_run_count = len([item for item in task_run_items if (item.get("status") or "") != "success"])

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("当前后台任务", "运行中" if task_status_value in ["queued", "running"] else "空闲")
    metric_col2.metric("已配置自动任务", len(task_defs))
    metric_col3.metric("最近执行条目", len(task_run_items))
    metric_col4.metric("失败条目", failed_run_count)


def render_current_bg_task_panel(current_bg_task_id, current_bg_task_status, task_status_value):
    """
    渲染当前后台任务状态面板。
    """
    if not current_bg_task_status:
        st.info("当前没有后台异步任务。你可以在“处理中心”发起视频处理，或在“订阅自动化”中创建定时任务。")
        return

    status_label_map = {
        "queued": "排队中",
        "running": "运行中",
        "success": "已完成",
        "failed": "失败",
    }
    with st.container(border=True):
        st.markdown(f"**任务 ID**：`{current_bg_task_id[:8]}`")
        st.caption(f"状态：`{status_label_map.get(task_status_value, task_status_value or 'unknown')}`")

        if task_status_value == "success":
            st.success("后台任务已完成。你可以清理状态后继续新任务，或在下方查看结果摘要。")
            result_text = str(current_bg_task_status.get("result") or "").strip()
            if result_text:
                with st.expander("查看本次结果", expanded=False):
                    st.write(result_text)
        elif task_status_value == "failed":
            st.error(f"后台任务失败：{current_bg_task_status.get('error', '未知错误')}")
        else:
            st.info("后台任务仍在执行中，页面会自动轮询刷新。")

        action_col1, action_col2 = st.columns([1, 1])
        with action_col1:
            if st.button("清理当前任务状态", key="task_center_clear_bg", use_container_width=True):
                st.session_state.bg_task_id = None
                st.rerun()
        with action_col2:
            if st.button("立即刷新任务状态", key="task_center_refresh_bg", use_container_width=True):
                st.rerun()


def render_recent_task_run_item(item):
    """
    渲染单条最近执行记录。
    """
    with st.container(border=True):
        head_c1, head_c2 = st.columns([4, 1])
        with head_c1:
            st.markdown(f"**{item.get('title') or '未命名任务'}**")
            meta_parts = []
            if item.get("channel_name"):
                meta_parts.append(f"频道：{item.get('channel_name')}")
            if item.get("created_at"):
                meta_parts.append(f"时间：{_parse_iso(item.get('created_at')).strftime('%m-%d %H:%M')}")
            if item.get("url"):
                meta_parts.append(f"[链接]({item.get('url')})")
            if meta_parts:
                st.caption(" | ".join(meta_parts))
        with head_c2:
            if item.get("status") == "success":
                st.success("成功", icon="✅")
            else:
                st.error("失败", icon="❌")

        if item.get("status") == "success":
            with st.expander("查看结果摘要", expanded=False):
                summary_content = item.get("summary") or ""
                if summary_content:
                    render_summary_content(summary_content, fact_title="🕵️ 新闻事实核查")
                else:
                    st.markdown("本次任务未返回可展示摘要。")
        else:
            st.caption(f"失败原因：{item.get('error') or '未知错误'}")


def render_recent_task_runs_panel(task_run_items):
    """
    渲染最近执行记录列表。
    """
    if not task_run_items:
        st.caption("暂无最近执行记录。")
        return

    recent_items = sorted(task_run_items, key=lambda item: item.get("created_at") or "", reverse=True)[:12]
    for item in recent_items:
        render_recent_task_run_item(item)


def render_task_logs_panel(task_logs):
    """
    渲染任务运行日志。
    """
    if task_logs:
        st.dataframe(task_logs[-50:], use_container_width=True, hide_index=True)
    else:
        st.caption("暂无运行日志。")


def render_task_center_page(current_bg_task_id, current_bg_task_status):
    """
    渲染任务中心页面，统一展示后台异步任务、最近执行记录与运行日志。
    """
    st.markdown("### 📋 任务中心")
    st.caption("集中查看后台异步任务、调度运行结果和最近错误，避免任务执行像黑箱。")

    _task_settings, task_defs, task_logs, task_runs, task_run_items, _task_processed_ids = _load_scheduled_state()
    task_status_value = (current_bg_task_status or {}).get("status") or "idle"

    render_task_center_metrics(task_status_value, task_defs, task_run_items)
    current_task_tab, recent_runs_tab, logs_tab = st.tabs(["🎯 当前任务", "🕘 最近执行", "🧾 运行日志"])

    with current_task_tab:
        render_current_bg_task_panel(current_bg_task_id, current_bg_task_status, task_status_value)

    with recent_runs_tab:
        render_recent_task_runs_panel(task_run_items)

    with logs_tab:
        render_task_logs_panel(task_logs)

    return task_status_value, task_logs, task_runs, task_run_items


def render_library_filters(history_count: int):
    """
    渲染资产库筛选栏。
    """
    filter_col1, filter_col2, filter_col3 = st.columns([4.2, 0.8, 1.2])
    with filter_col1:
        hist_kw = st.text_input("搜索历史记录 (标题/URL/内容)", key="hist_kw")
    with filter_col2:
        search_body = st.checkbox("全文搜索", value=True)
    with filter_col3:
        if history_count > 0:
            if st.button("清空历史", use_container_width=True):
                save_history([])
                st.rerun()

    return hist_kw, search_body


def history_entry_matches(entry, hist_kw, search_body):
    """
    判断历史记录是否命中当前筛选条件。
    """
    if not hist_kw:
        return True

    kw = hist_kw.lower().strip()
    title_hit = kw in (entry.get("title") or "").lower()
    url_hit = kw in (entry.get("video_url") or "").lower()
    body_hit = False
    if search_body and not (title_hit or url_hit):
        raw = entry.get("summary_text") or ""
        summary_md_for_search, fact_md_for_search = _parse_summary_for_ui(raw)
        body_text = (summary_md_for_search or raw) + "\n" + (fact_md_for_search or "")
        body_hit = kw in body_text.lower()

    return title_hit or url_hit or body_hit


def render_history_entry(entry):
    """
    渲染单条历史记录。
    """
    with st.expander(f"{entry.get('timestamp')[:16].replace('T', ' ')} | {entry.get('title')}", expanded=False):
        st.caption(f"来源: {'⏰ 定时任务' if entry.get('source_type') == 'schedule' else '🎬 单次任务'} | URL: {entry.get('video_url')}")

        render_summary_content(
            entry.get("summary_text") or "",
            fact_title="🕵️ 新闻事实核查",
        )


def render_library_page():
    """
    渲染内容资产库，统一浏览历史摘要与全文检索结果。
    """
    st.markdown("### 🗂️ 内容资产库")
    st.caption("统一沉淀单次处理、手动粘贴、扩展桥接和定时任务产出的内容结果。")

    history = load_history() or []
    hist_kw, search_body = render_library_filters(len(history))

    if not history:
        st.info("暂无历史记录，等你生成第一条总结后会自动沉淀到这里。")
        return

    matched_entries = [
        entry for entry in history
        if history_entry_matches(entry, hist_kw, search_body)
    ]
    st.caption(f"共 {len(history)} 条历史记录，当前命中 {len(matched_entries)} 条")

    for entry in matched_entries:
        render_history_entry(entry)


def render_settings_metrics(task_status_value):
    """
    渲染设置与诊断页顶部指标。
    """
    runtime_diag = str(build_runtime_version_diagnostics() or "").strip()
    runtime_lines = [item.strip() for item in runtime_diag.split(";") if item.strip()]
    render_info = get_render_build_info()
    if render_info["is_render"] == "yes":
        runtime_summary = render_info["commit_short"] or "unknown"
        runtime_caption = f"deploy={_short_display(render_info['deploy_id'] or 'n/a', 18)} | branch={render_info['branch'] or 'unknown'}"
    else:
        runtime_summary = "本地开发版" if "expected_commit=latest-local" in runtime_diag else "运行中"
        runtime_caption = f"commit={render_info['commit_short'] or 'local'} | deploy=local"
    task_summary = "运行中" if task_status_value in ["queued", "running"] else "空闲"
    bridge_summary = "已连接" if st.session_state.manual_bridge_meta else "暂无"

    diag_col1, diag_col2, diag_col3 = st.columns(3)

    with diag_col1:
        with st.container(border=True):
            st.caption("运行版本")
            st.markdown(f"### {runtime_summary}")
            st.caption(runtime_caption)

    with diag_col2:
        with st.container(border=True):
            st.caption("后台任务")
            st.markdown(f"### {task_summary}")
            st.caption("用于观察当前后台抓取与总结状态")

    with diag_col3:
        with st.container(border=True):
            st.caption("Bridge 元信息")
            st.markdown(f"### {bridge_summary}")
            st.caption("用于判断扩展或本地工具是否已回传上下文")

    with st.expander("查看运行版本详情", expanded=False):
        if runtime_lines:
            st.code("\n".join(runtime_lines), language="text")
        else:
            st.caption("暂无可展示的运行版本诊断信息。")

    with st.expander("查看 Render 部署信息", expanded=False):
        if render_info["is_render"] == "yes":
            st.json(
                {
                    "commit": render_info["commit"] or "unknown",
                    "branch": render_info["branch"] or "unknown",
                    "deploy_id": render_info["deploy_id"] or "未暴露 deploy id",
                    "service_id": render_info["service_id"] or "unknown",
                    "service_name": render_info["service_name"] or "unknown",
                    "service_type": render_info["service_type"] or "unknown",
                    "external_url": render_info["external_url"] or "",
                    "repo_slug": render_info["repo_slug"] or "",
                },
                expanded=False,
            )
            if not render_info["deploy_id"]:
                st.caption("当前 Render 环境变量未明确暴露 deploy id；页面会优先显示 commit、branch 与 service 信息。")
        else:
            st.caption("当前为本地运行环境，未检测到 Render 部署变量。")


def render_bridge_diagnostics_panel():
    """
    渲染 bridge 元信息与诊断内容。
    """
    with st.expander("查看提取与桥接诊断", expanded=False):
        if st.session_state.manual_bridge_meta:
            bridge_context = build_manual_bridge_context(st.session_state.manual_bridge_meta)
            if bridge_context.get("summary"):
                st.info(bridge_context["summary"])
            if bridge_context.get("details"):
                st.caption(bridge_context["details"])
            bridge_meta_text = format_manual_bridge_meta(st.session_state.manual_bridge_meta)
            if bridge_meta_text:
                st.code(bridge_meta_text)
        else:
            st.caption("当前还没有可展示的 bridge 诊断数据。")


def render_guestbook_form():
    """
    渲染留言表单并处理提交。
    """
    with st.form("guestbook_form", clear_on_submit=True):
        user_name = st.text_input("昵称", value="User", max_chars=20)
        message = st.text_area("留言内容", height=100)
        submitted = st.form_submit_button("发布留言")

        if submitted and message.strip():
            guestbook = load_guestbook()
            new_msg = {
                "id": str(uuid.uuid4()),
                "timestamp": _iso(_now()),
                "user": user_name.strip() or "Anonymous",
                "content": message.strip(),
            }
            guestbook.insert(0, new_msg)
            save_guestbook(guestbook)
            st.success("留言已发布")
            st.rerun()


def render_runtime_history_panel(task_logs, task_runs, task_run_items):
    """
    渲染运行日志与历史概览。
    """
    with st.expander("📜 运行日志 & 历史", expanded=False):
        tab_log, tab_hist = st.tabs(["日志", "历史"])
        with tab_log:
            if task_logs:
                st.dataframe(task_logs[-50:], use_container_width=True, hide_index=True)
            else:
                st.caption("无日志")
        with tab_hist:
            daily_runs, _ = _group_runs_by_day(task_runs, task_run_items)
            if not daily_runs:
                st.caption("无历史")
            else:
                for day in daily_runs[:5]:
                    st.markdown(f"**{day.get('date')}**: 新增 {day.get('new_items')} | 成功 {day.get('success_items')}")


def render_guestbook_section(task_logs, task_runs, task_run_items):
    """
    渲染留言列表与附带的运行历史面板。
    """
    guestbook = load_guestbook()
    if not guestbook:
        st.info("暂无留言，快来抢沙发吧！")
        return

    for msg in guestbook:
        with st.chat_message("user" if msg.get("user") == "User" else "assistant", avatar="👤"):
            st.markdown(f"**{msg.get('user')}** <span style='color:gray; font-size:0.8em'> {msg.get('timestamp')[:16].replace('T', ' ')}</span>", unsafe_allow_html=True)
            st.markdown(msg.get("content"))

    render_runtime_history_panel(task_logs, task_runs, task_run_items)


def render_settings_diagnostics_page(task_status_value, task_logs, task_runs, task_run_items):
    """
    渲染设置与诊断页面，聚合运行状态、bridge 信息与反馈入口。
    """
    st.markdown("### 🛠️ 设置与诊断")
    st.caption("集中放置运行诊断、桥接状态和反馈入口，降低问题排查成本。")
    st.caption(f"当前双模型流水线：`{pipeline_model_label}`")

    render_settings_metrics(task_status_value)
    render_bridge_diagnostics_panel()
    render_issue_report_box(
        "设置与诊断页",
        source_url=st.session_state.get("manual_source_url") or "",
        extra={
            "task_status": task_status_value or "",
            "task_log_count": len(task_logs or []),
            "task_run_count": len(task_runs or []),
            "task_run_item_count": len(task_run_items or []),
        },
        key_prefix="settings_diag",
        expanded=False,
        box_title="诊断信息与问题上报",
    )

    st.divider()
    st.markdown("#### 💬 反馈与建议")
    st.caption("原“留言板”功能先保留在这里，后续可逐步升级为问题反馈与诊断上报中心。")
    render_guestbook_form()

    st.divider()
    render_guestbook_section(task_logs, task_runs, task_run_items)


def do_video_summary_single(url, manual=True, fetch_duration=0.0):
    """
    基于当前字幕内容生成单视频 AI 总结。
    """
    if not st.session_state.transcript_text:
        if manual:
            st.warning("请先抓取字幕")
        return

    reset_video_fact_check_state()
    print(
        "VideoSummarySingle: "
        f"manual={bool(manual)}, "
        f"url={str(url or '').strip()}, "
        f"fetch_duration={float(fetch_duration):.2f}, "
        f"transcript_len={len(str(st.session_state.transcript_text or ''))}, "
        "enable_fact_check=False"
    , flush=True)
    t_sum_start = time.time()
    with st.spinner(f"正在请求 AI 总结 ({pipeline_model_label})..."):
        summary, err = internal_summarize(
            st.session_state.transcript_text,
            summary_model_selected,
            fact_check_model_selected,
            enable_fact_check=False,
        )

    sum_duration = time.time() - t_sum_start
    total_duration = fetch_duration + sum_duration
    st.session_state.summary_duration = {
        "fetch": fetch_duration,
        "summary": sum_duration,
        "total": total_duration,
    }

    if err:
        print(f"VideoSummarySingle: failed error={err}", flush=True)
        st.error(f"总结失败: {err}")
        render_issue_report_box(
            "单视频总结失败",
            source_url=url,
            error_text=err,
            extra={"mode": "single_video_summary", "manual": bool(manual)},
            key_prefix="video_summary_fail",
            expanded=False,
        )
        return

    print(
        "VideoSummarySingle: success "
        f"url={str(url or '').strip()}, "
        f"summary_len={len(str(summary or ''))}, "
        f"duration={sum_duration:.2f}"
    , flush=True)
    st.session_state.summary_text = summary
    start_video_fact_check_async(url, st.session_state.transcript_text, summary)
    if manual:
        st.success(f"总结完成 | AI生成耗时: {sum_duration:.1f}s")

    try:
        add_history_entry("single", url, summary, st.session_state.transcript_text)
    except Exception as e_hist:
        print(f"Failed to save history: {e_hist}")


if st.session_state.get("video_extension_auto_summary_pending"):
    pending_summary_url = str(st.session_state.get("video_extension_auto_summary_url") or "").strip()
    pending_fetch_duration = float(st.session_state.get("video_extension_auto_summary_fetch_duration") or 0.0)
    st.session_state.video_extension_auto_summary_pending = False
    st.session_state.video_extension_auto_summary_url = ""
    st.session_state.video_extension_auto_summary_fetch_duration = 0.0
    do_video_summary_single(
        pending_summary_url,
        manual=False,
        fetch_duration=pending_fetch_duration,
    )


def remember_current_video_url(url: str = "") -> str:
    """把当前视频链接持久化到独立 key，避免 rerun 时依赖 widget 状态。"""
    candidate = str(url or "").strip()
    if candidate:
        st.session_state.current_video_url = candidate
        return candidate
    return str(st.session_state.get("current_video_url") or "").strip()


def get_current_video_url(url: str = "") -> str:
    """统一解析当前视频链接，避免 rerun 后局部变量丢失。"""
    remembered = remember_current_video_url(url)
    if remembered:
        return remembered
    return str(st.session_state.get("input_url") or "").strip()


def do_video_fetch_single(url):
    """
    抓取单视频字幕，并在完成后触发总结。
    """
    url = get_current_video_url(url)
    if not url:
        st.warning("请输入视频链接")
        return

    status_container = st.empty()
    status_container.info("正在初始化...")

    try:
        with st.status("🔍 网络预检中...", expanded=False) as status:
            eff_proxy, pac_note = get_effective_proxy(proxy_input, use_system_proxy)
            status.write(f"当前代理: {eff_proxy or '无 (直连)'}")
            if pac_note:
                status.info(pac_note)

            net_err = check_network(eff_proxy, timeout=5.0)
            if net_err:
                status.update(label="⚠️ 网络预检失败", state="error", expanded=True)
                st.warning(f"无法连接 Google/YouTube。\n错误信息：{net_err}")
            else:
                status.update(label="✅ 网络预检通过", state="complete")

        status_container.info("正在抓取字幕/转写音频...")
        progress_bar = st.progress(0)
        t_start_all = time.time()

        def update_progress(progress_value, progress_text):
            progress_bar.progress(progress_value, text=progress_text)

        text, err = internal_fetch_transcript(url, update_progress)
        fetch_duration = time.time() - t_start_all

        if err:
            progress_bar.empty()
            status_container.error("❌ 抓取失败")
            st.error(err)
            render_issue_report_box(
                "视频抓取失败",
                source_url=url,
                error_text=err,
                extra={"mode": "video_fetch"},
                key_prefix="video_fetch_fail",
                expanded=False,
            )
            return

        _whisper_device_info, text = _extract_whisper_device_info(text)
        st.session_state.whisper_device_tag = ""
        st.session_state.transcript_text = text

        msg = f"🎉 成功获取字幕！ | 耗时: {fetch_duration:.1f}s"
        status_container.success(msg)

        time.sleep(0.5)
        progress_bar.empty()
        do_video_summary_single(url, manual=False, fetch_duration=fetch_duration)
    except Exception as e:
        status_container.error("❌ 执行异常")
        st.error(f"{e}")
        st.code(traceback.format_exc())
        render_issue_report_box(
            "视频抓取异常",
            source_url=url,
            error_text=str(e),
            extra={"mode": "video_fetch_exception", "traceback": traceback.format_exc()[-2000:]},
            key_prefix="video_fetch_exception",
            expanded=False,
        )


def reset_video_extension_request_state(clear_result: bool = True):
    """重置视频插件请求状态，避免旧请求结果污染后续流程。"""
    st.session_state.video_extension_request_pending = False
    st.session_state.video_extension_request_url = ""
    st.session_state.video_extension_request_id = ""
    st.session_state.video_extension_request_component_key = ""
    if clear_result:
        st.session_state.video_extension_request_result = None
        st.session_state.video_extension_request_debug_text = ""


def begin_video_extension_request(url: str) -> tuple[bool, str]:
    """初始化一次插件抓取请求，实际结果由后续 rerun 异步消费。"""
    url = get_current_video_url(url)
    if not url:
        return False, ""

    request_id = f"video_extension_request_{uuid.uuid4().hex}"
    st.session_state.video_extension_request_pending = True
    st.session_state.video_extension_request_url = url
    st.session_state.video_extension_request_id = request_id
    st.session_state.video_extension_request_component_key = f"video_extension_request_{request_id}"
    st.session_state.video_extension_request_result = None
    return True, "已向插件发起抓取请求，正在等待响应..."


def try_video_extension_first() -> tuple[str, str, str]:
    """
    轮询当前视频插件请求状态。
    返回 (status, message, url)：
    - idle: 当前没有待处理请求
    - waiting: 已发起请求，等待插件回包
    - payload_ready: 插件已返回 payloadId，等待主站消费 bridge payload
    - fallback: 插件流程失败，不再自动回退主站音频/转写链路
    """
    if not bool(st.session_state.get("video_extension_request_pending")):
        return "idle", "", ""

    url = get_current_video_url(st.session_state.get("video_extension_request_url") or "")
    if not url:
        reset_video_extension_request_state()
        return "idle", "", ""

    result = request_extension_summarize_flow(
        url,
        request_id=str(st.session_state.get("video_extension_request_id") or "").strip(),
        component_key=str(st.session_state.get("video_extension_request_component_key") or "").strip(),
    )
    normalized_result = normalize_extension_request_result(result)
    st.session_state.video_extension_request_result = normalized_result
    st.session_state.video_extension_request_debug_text = ""
    if normalized_result is None:
        return "waiting", "已调用插件抓取，正在等待插件响应...", url

    if not isinstance(normalized_result, dict):
        reset_video_extension_request_state()
        return "fallback", "未检测到可用插件响应，且未再自动回退主站抓取。", url

    if not bool(normalized_result.get("ok")):
        error_text = str(normalized_result.get("error") or "").strip()
        if error_text == "extension_request_timeout":
            error_text = "extension_request_timeout:bridge_waited_150s_no_plugin_reply"
        helper_text = str(normalized_result.get("helperMessage") or normalized_result.get("helper_message") or "").strip()
        debug_obj = normalized_result.get("debug") if isinstance(normalized_result.get("debug"), dict) else None
        tool_version_text = ""
        debug_summary = ""
        debug_lines: list[str] = []
        extraction_logs: list[str] = []
        if isinstance(debug_obj, dict):
            tool_version_text = str(debug_obj.get("toolVersion") or debug_obj.get("tool_version") or "").strip()
            attempts = debug_obj.get("attempts")
            extraction_logs = debug_obj.get("extractionLogs") if isinstance(debug_obj.get("extractionLogs"), list) else []
            if isinstance(attempts, list) and attempts:
                parts: list[str] = []
                for item in attempts[:6]:
                    if not isinstance(item, dict):
                        continue
                    stage = str(item.get("stage") or "").strip()
                    ok_flag = bool(item.get("ok"))
                    item_error = str(item.get("error") or "").strip()
                    item_reason = str(item.get("reason") or "").strip()
                    part = stage or "unknown_stage"
                    part += ":ok" if ok_flag else f":{item_error or 'failed'}"
                    if item_reason:
                        part += f"({item_reason})"
                    parts.append(part)
                for item in attempts:
                    if not isinstance(item, dict):
                        continue
                    debug_lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
                if parts:
                    debug_summary = " | ".join(parts)
        if debug_lines:
            st.session_state.video_extension_request_debug_text = "\n".join(debug_lines)
        reset_video_extension_request_state(clear_result=False)
        message = f"插件抓取未接管（{error_text or 'unknown_error'}）。请确认视频是否确实开启了字幕，或手动尝试刷新页面后再试。"
        if tool_version_text:
            message += f" 当前扩展版本：v{tool_version_text}。"
        if helper_text:
            message += f" {helper_text}"
        if debug_summary:
            message += f" 调试：{debug_summary}"
        return "fallback", message, url

    payload_id = str(normalized_result.get("payloadId") or normalized_result.get("payload_id") or "").strip()
    if not payload_id:
        reset_video_extension_request_state(clear_result=False)
        return "fallback", "插件未返回 payloadId，且未再自动回退主站抓取。", url

    st.session_state.video_extension_payload_id = payload_id
    st.session_state.video_extension_last_payload_id = ""
    reset_video_extension_request_state(clear_result=False)
    return "payload_ready", "已调用插件抓取，主站正在读取 bridge 回传...", url


def do_video_check_single(url):
    """
    检测当前视频可用字幕列表。
    """
    url = get_current_video_url(url)
    if not url:
        st.warning("请输入视频链接")
        return
    try:
        with st.spinner("检测中..."):
            video_id, _, _ = get_transcript_from_input(url, languages)
            api = build_api(proxy_input, float(timeout), use_system_proxy, int(retries))
            report = list_available_transcripts(api, video_id)
            st.text(report)
    except Exception as e:
        st.error(format_error(e))
        render_issue_report_box(
            "字幕检测失败",
            source_url=url,
            error_text=format_error(e),
            extra={"mode": "video_check"},
            key_prefix="video_check_fail",
            expanded=False,
        )


def render_video_summary_section():
    """
    渲染视频总结结果与耗时信息。
    """
    if not st.session_state.summary_text:
        return

    sync_video_fact_check_state()
    initial_status = str(st.session_state.get("video_fact_check_status") or "").strip()
    run_every = "3s" if initial_status in {"queued", "running"} else None

    @st.fragment(run_every=run_every)
    def _render_video_summary_fragment():
        sync_video_fact_check_state()
        st.markdown("### 📝 AI 总结")
        if "summary_duration" in st.session_state and st.session_state.summary_duration:
            duration_info = st.session_state.summary_duration
            fetch_t = duration_info.get("fetch", 0)
            sum_t = duration_info.get("summary", 0)
            total_t = duration_info.get("total", 0)
            st.caption(f"⏱️ **总耗时: {total_t:.1f}s** (文本抓取: {fetch_t:.1f}s | AI 生成: {sum_t:.1f}s)")
        st.caption(f"🤖 模型流水线：{pipeline_model_label}")

        render_summary_content(
            st.session_state.summary_text,
            fact_title="🕵️ 新闻事实核查",
        )
        status = str(st.session_state.get("video_fact_check_status") or "").strip()
        note = str(st.session_state.get("video_fact_check_note") or "").strip()
        if status in {"queued", "running"}:
            st.caption("🕵️ 新闻核查正在后台补跑，完成后会自动刷新到右侧区域。")
            if note:
                st.caption(note)
        elif status == "skipped":
            if note:
                st.caption(f"🕵️ {note}")
        elif status == "error":
            st.warning(f"新闻核查补跑失败：{str(st.session_state.get('video_fact_check_error') or '').strip()}")
        elif status == "success" and note:
            st.caption(f"🕵️ {note}")

        st.divider()

        if run_every is not None and status not in {"queued", "running"}:
            st.rerun()

    _render_video_summary_fragment()

    # 当前模式已关闭音频下载/Whisper 转写兜底，不再展示相关脚注。


def render_video_transcript_section():
    """
    渲染视频字幕查看区域。
    """
    if not st.session_state.transcript_text:
        return

    with st.expander("查看字幕原文", expanded=False):
        transcript_view_mode = st.radio(
            "字幕视图",
            ["阅读版", "原始版"],
            horizontal=True,
            index=0,
            key="transcript_view_mode",
        )
        if transcript_view_mode == "原始版":
            st.caption("原始版仅移除了内部调试标签，适合排查问题。")
            display_text = _raw_transcript_for_display(st.session_state.transcript_text)
        else:
            st.caption("阅读版已自动清理内部标签，并按更适合阅读的形式展示。")
            display_text = _clean_transcript_for_display(st.session_state.transcript_text)
        st.text_area("字幕内容", display_text, height=360)


def render_video_processing_tab():
    """
    渲染视频处理入口，包括抓取字幕、异步处理、字幕检测和结果展示。
    """
    st.info("💡 支持输入：\n- YouTube 视频链接 / ID\n- Bilibili 视频链接 / BV号")
    url = st.text_input(
        "视频链接或 ID",
        key="input_url",
        placeholder="https://www.youtube.com/watch?v=... 或 https://www.bilibili.com/video/BV...",
    )
    remember_current_video_url(url)
    resolved_url = get_current_video_url(url)
    extension_status, extension_message, extension_url = try_video_extension_first()
    if extension_status == "waiting" and extension_message:
        st.info(extension_message)
    elif extension_status == "payload_ready":
        st.rerun()
    elif extension_status == "fallback":
        if extension_message:
            st.error(extension_message)
        debug_text = str(st.session_state.get("video_extension_request_debug_text") or "").strip()
        if debug_text:
            with st.expander("查看插件桥接链调试明细", expanded=False):
                st.code(debug_text, language="json")
        
        # 获取当前的请求结果以提取日志
        current_result = st.session_state.get("video_extension_request_result")
        extraction_logs = []
        if isinstance(current_result, dict):
            # 尝试从不同位置提取日志
            detection = current_result.get("detection")
            if isinstance(detection, dict):
                extraction_logs = detection.get("extractionLogs", [])
            
            if not extraction_logs:
                debug_obj = current_result.get("debug")
                if isinstance(debug_obj, dict):
                    detection_inner = debug_obj.get("detection")
                    if isinstance(detection_inner, dict):
                        extraction_logs = detection_inner.get("extractionLogs", [])
        
        if isinstance(extraction_logs, list) and extraction_logs:
            with st.expander("查看插件文本提取过程日志", expanded=True):
                for log_line in extraction_logs:
                    st.write(f"- {log_line}")

        st.divider()
        col_fb1, col_fb2 = st.columns([3, 1])
        with col_fb1:
            st.warning("💡 插件模式抓取失败。请确认插件已更新至最新版并已在当前页面启用。")
        with col_fb2:
            if st.button("🔄 重置状态", key="btn_reset_extension", use_container_width=True):
                reset_video_extension_request_state(clear_result=True)
                st.rerun()
        
        st.caption("提示：本项目依赖插件提取页面文稿。如果该视频没有平台字幕，插件将无法获取文本。")
        return

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        fetch_btn = st.button("🚀 一键抓取并总结", type="primary", use_container_width=True, key="btn_single_fetch")
    with col2:
        summary_btn = st.button("🤖 仅重新生成总结", use_container_width=True, key="btn_single_sum")
    with col3:
        check_btn = st.button("🔍 检测可用字幕", use_container_width=True, key="btn_single_check")

    if fetch_btn:
        if not resolved_url:
            st.warning("请输入视频链接")
            return
        handled_by_extension, extension_message = begin_video_extension_request(resolved_url)
        if handled_by_extension:
            st.info(extension_message)
            st.rerun()
        st.warning("当前入口已切换为插件优先模式；如果未触发插件，请检查扩展是否已在当前页面注入。")
    if summary_btn:
        if not resolved_url:
            st.warning("请输入视频链接")
            return
        do_video_summary_single(resolved_url)
    if check_btn:
        if not resolved_url:
            st.warning("请输入视频链接")
            return
        do_video_check_single(resolved_url)

    render_video_summary_section()
    render_video_transcript_section()


def render_manual_bridge_status():
    """
    渲染文本模式下的 bridge 状态与元信息。
    """
    if bridge_payload_waiting:
        st.caption("正在等待浏览器扩展通过 bridge 发送 transcript...")
        if bridge_payload_error:
            st.caption(f"bridge 诊断：`{bridge_payload_error}`")

    if not st.session_state.manual_bridge_meta:
        return

    bridge_context = build_manual_bridge_context(st.session_state.manual_bridge_meta)
    if bridge_context.get("summary"):
        st.info(bridge_context["summary"])
    if bridge_context.get("details"):
        st.caption(bridge_context["details"])

    bridge_meta_text = format_manual_bridge_meta(st.session_state.manual_bridge_meta)
    if bridge_meta_text:
        with st.expander("查看 bridge 元信息", expanded=False):
            st.caption(bridge_meta_text)


def run_manual_transcript_summary(manual_source_url, manual_transcript, auto_paste_sum):
    """
    对手动粘贴或 bridge 自动注入的字幕文本执行总结。
    """
    if not manual_transcript.strip():
        st.warning("请先粘贴字幕文本。")
        return

    current_payload_id = st.session_state.manual_auto_payload_id if auto_paste_sum else ""
    t_manual_start = time.time()
    with st.spinner(f"正在请求 AI 总结 ({pipeline_model_label})..."):
        summary, err = internal_summarize(
            manual_transcript.strip(),
            summary_model_selected,
            fact_check_model_selected,
        )
    duration = time.time() - t_manual_start

    if current_payload_id:
        st.session_state.manual_last_payload_id = current_payload_id
        st.session_state.manual_auto_payload_id = ""
        try:
            st.query_params.clear()
        except Exception:
            pass

    if err:
        st.error(f"总结失败: {err}")
        render_issue_report_box(
            "粘贴文本总结失败",
            source_url=manual_source_url,
            error_text=err,
            extra={"mode": "manual_transcript_summary"},
            key_prefix="manual_summary_fail",
            expanded=False,
        )
        return

    st.session_state.manual_summary_text = summary
    st.session_state.manual_summary_duration = {"summary": duration}

    try:
        history_source_type = "manual_transcript"
        manual_meta = st.session_state.manual_bridge_meta or {}
        if manual_meta.get("source_kind") == "extension":
            history_source_type = "extension_bridge"
        elif manual_meta.get("source_kind") == "local_tool":
            history_source_type = "local_tool_bridge"
        add_history_entry(history_source_type, manual_source_url.strip(), summary, manual_transcript.strip())
    except Exception as e_hist:
        print(f"Failed to save manual transcript history: {e_hist}")

    st.success(f"总结完成 | AI生成耗时: {duration:.1f}s")


def render_manual_summary_section():
    """
    渲染手动字幕总结结果与原文查看区域。
    """
    if not st.session_state.manual_summary_text:
        return

    st.markdown("### 📝 字幕总结")
    manual_dur = float((st.session_state.manual_summary_duration or {}).get("summary") or 0.0)
    if manual_dur:
        st.caption(f"⏱️ AI生成耗时: {manual_dur:.1f}s")
    st.caption(f"🤖 模型流水线：{pipeline_model_label}")

    if st.session_state.manual_bridge_meta:
        bridge_context = build_manual_bridge_context(st.session_state.manual_bridge_meta)
        if bridge_context.get("summary"):
            st.info(f"本次总结来源：{bridge_context['summary']}")
        if bridge_context.get("details"):
            st.caption(bridge_context["details"])
        bridge_meta_text = format_manual_bridge_meta(st.session_state.manual_bridge_meta)
        if bridge_meta_text:
            with st.expander("查看本次总结的 bridge 元信息", expanded=False):
                st.caption(bridge_meta_text)

    render_summary_content(
        st.session_state.manual_summary_text,
        fact_title="🕵️ 新闻事实核查",
    )
    with st.expander("查看粘贴的字幕原文", expanded=False):
        st.text_area("字幕原文", st.session_state.manual_transcript_text, height=320, key="manual_transcript_view")


def render_text_processing_tab():
    """
    渲染粘贴文本入口，兼容扩展 bridge 自动回填与手动粘贴总结。
    """
    st.info("💡 适合浏览器扩展、第三方 transcript 或你手动复制的字幕文本。这里不负责抓取，只负责基于文本做总结。")
    render_manual_bridge_status()

    manual_source_url = st.text_input(
        "来源链接（可选）",
        key="manual_source_url",
        placeholder="https://www.youtube.com/watch?v=... 或 https://www.bilibili.com/video/BV...",
    )
    manual_transcript = st.text_area(
        "粘贴 transcript / 字幕文本",
        height=260,
        key="manual_transcript_text",
        placeholder="把浏览器扩展提取到的字幕文本粘贴到这里...",
    )
    paste_col1, paste_col2 = st.columns([1, 3])
    with paste_col1:
        paste_sum_btn = st.button("📝 总结字幕文本", type="primary", use_container_width=True, key="btn_manual_sum")
    with paste_col2:
        st.caption("适合作为 YouTube/B站抓取失败时的稳定兜底入口。")

    auto_paste_sum = bool(
        st.session_state.manual_auto_payload_id
        and st.session_state.manual_auto_payload_id != st.session_state.manual_last_payload_id
        and manual_transcript.strip()
    )
    if auto_paste_sum:
        st.caption("已接收到浏览器扩展传来的 transcript，正在自动开始总结...")

    if paste_sum_btn or auto_paste_sum:
        run_manual_transcript_summary(manual_source_url, manual_transcript, auto_paste_sum)

    render_manual_summary_section()


def save_document_result(source_key: str, result, duration: float):
    """
    保存文档提取与总结结果到会话状态。
    """
    extracted = result["extract"]
    summary_result = result["summary"]
    fact_check_plan = result.get("fact_check_plan") or {}
    st.session_state.document_results[source_key] = {
        "raw_text": extracted["raw_text"],
        "clean_text": extracted["clean_text"],
        "summary_text": summary_result["summary_markdown"],
        "fact_check_text": str(result.get("fact_check_markdown") or ""),
        "source_url": str(extracted.get("source_url") or ""),
        "meta": {
            **extracted,
            **summary_result,
            "fact_check_plan": fact_check_plan,
            "duration": duration,
        },
    }


def render_document_result(source_key: str):
    """
    渲染指定来源的文档总结结果。
    """
    result_state = st.session_state.document_results.get(source_key) or {}
    summary_text = str(result_state.get("summary_text") or "").strip()
    if not summary_text:
        return

    raw_text = str(result_state.get("raw_text") or "")
    clean_text = str(result_state.get("clean_text") or "")
    fact_check_content = str(result_state.get("fact_check_text") or "")
    source_url_state = str(result_state.get("source_url") or "")
    doc_meta = result_state.get("meta") or {}

    st.markdown("### 📄 文档总结")
    file_name = doc_meta.get("file_name", "未命名文档")
    file_type = str(doc_meta.get("file_type") or "").upper() or "DOC"
    char_count = int(doc_meta.get("char_count") or 0)
    page_count = doc_meta.get("page_count")
    chunk_count = int(doc_meta.get("chunk_count") or 1)
    strategy = "分块总结" if doc_meta.get("strategy") == "chunked" else "直接总结"
    duration = float(doc_meta.get("duration") or 0.0)
    source_url = str(doc_meta.get("source_url") or source_url_state or "").strip()
    ocr_used = bool(doc_meta.get("ocr_used", False))
    fact_check_plan = doc_meta.get("fact_check_plan") or {}
    doc_type = str(fact_check_plan.get("document_type") or "unknown")
    should_fact_check = bool(fact_check_plan.get("should_fact_check", False))
    fact_check_reason = str(fact_check_plan.get("reason") or "").strip()
    recommended_claim_count = int(fact_check_plan.get("recommended_claim_count") or 0)

    meta_parts = [
        f"文件：`{file_name}`",
        f"类型：`{file_type}`",
        f"正文：`{char_count}` 字符",
        f"策略：`{strategy}`",
        f"分块：`{chunk_count}`",
    ]
    if page_count:
        meta_parts.append(f"页数：`{page_count}`")
    if duration:
        meta_parts.append(f"耗时：`{duration:.1f}s`")
    if ocr_used:
        meta_parts.append("OCR：`已启用`")
    meta_parts.append(f"文档判定：`{doc_type}`")
    st.caption(" | ".join(meta_parts))
    if source_url:
        st.caption(f"来源链接：[{source_url}]({source_url})")
    if fact_check_reason:
        st.caption(f"事实核查判定：{'已开启' if should_fact_check else '已跳过'}。{fact_check_reason}")

    if fact_check_content:
        render_summary_fact_check(
            summary_text,
            fact_check_content,
            fact_title="🕵️ 关键声明事实核查",
            fact_tab_label="🕵️ 关键声明核查",
        )
    else:
        st.markdown(summary_text)
        if should_fact_check and recommended_claim_count > 0:
            st.warning(f"⚠️ 文档已被判定为适合事实核查，但本次未成功生成核查结果。预期核查关键声明约 {recommended_claim_count} 条。")
        else:
            st.info("📝 当前文档功能已支持本地上传、在线链接、PPTX 和扫描 PDF OCR 回退。系统会自动判断是否需要关键声明事实核查。")

    with st.expander("查看文档原文", expanded=False):
        doc_view_mode = st.radio(
            "文档视图",
            ["阅读版", "原始版"],
            horizontal=True,
            index=0,
            key=f"document_view_mode_{source_key}",
        )
        if doc_view_mode == "原始版":
            st.caption("原始版为文档提取后的原始文本，适合排查解析问题。")
            display_text = raw_text
        else:
            st.caption("阅读版为清洗后的正文文本，更适合直接阅读。")
            display_text = clean_text
        st.text_area("文档内容", display_text, height=420, key=f"document_content_{source_key}")


def run_uploaded_document_summary(uploaded_doc):
    """
    执行本地上传文档的提取与总结。
    """
    if not uploaded_doc:
        st.warning("请先上传文档。")
        return

    status_container = st.empty()
    progress_bar = st.progress(0)
    status_container.info("正在准备文档总结...")
    t_doc_start = time.time()

    def update_doc_progress(pct, message):
        progress_bar.progress(max(0, min(100, int(pct))), text=message)

    try:
        result, err = internal_summarize_document(
            uploaded_doc.name,
            uploaded_doc.getvalue(),
            model_selected,
            update_doc_progress,
        )
        doc_duration = time.time() - t_doc_start
        if err:
            progress_bar.empty()
            status_container.error("❌ 文档总结失败")
            st.error(err)
            render_issue_report_box(
                "上传文档总结失败",
                error_text=err,
                extra={"mode": "document_upload_summary", "file_name": uploaded_doc.name},
                key_prefix="doc_upload_fail",
                expanded=False,
            )
            return

        save_document_result("upload", result, doc_duration)
        progress_bar.empty()
        status_container.success(f"✅ 文档总结完成！耗时: {doc_duration:.1f}s")
    except Exception as e:
        progress_bar.empty()
        status_container.error("❌ 文档处理异常")
        st.error(str(e))
        st.code(traceback.format_exc())
        render_issue_report_box(
            "上传文档处理异常",
            error_text=str(e),
            extra={"mode": "document_upload_exception", "traceback": traceback.format_exc()[-2000:]},
            key_prefix="doc_upload_exception",
            expanded=False,
        )


def run_document_url_summary(doc_url):
    """
    执行在线文档或文章链接的抓取与总结。
    """
    if not doc_url.strip():
        st.warning("请输入在线链接。")
        return

    status_container = st.empty()
    progress_bar = st.progress(0)
    status_container.info("正在抓取在线内容...")
    t_doc_start = time.time()

    def update_doc_url_progress(pct, message):
        progress_bar.progress(max(0, min(100, int(pct))), text=message)

    try:
        result, err = internal_summarize_document_url(
            doc_url.strip(),
            model_selected,
            update_doc_url_progress,
        )
        doc_duration = time.time() - t_doc_start
        if err:
            progress_bar.empty()
            status_container.error("❌ 在线文档总结失败")
            st.error(err)
            render_issue_report_box(
                "在线文档总结失败",
                source_url=doc_url,
                error_text=err,
                extra={"mode": "document_url_summary"},
                key_prefix="doc_url_fail",
                expanded=False,
            )
            return

        save_document_result("url", result, doc_duration)
        progress_bar.empty()
        status_container.success(f"✅ 在线内容总结完成！耗时: {doc_duration:.1f}s")
    except Exception as e:
        progress_bar.empty()
        status_container.error("❌ 在线内容处理异常")
        st.error(str(e))
        st.code(traceback.format_exc())
        render_issue_report_box(
            "在线内容处理异常",
            source_url=doc_url,
            error_text=str(e),
            extra={"mode": "document_url_exception", "traceback": traceback.format_exc()[-2000:]},
            key_prefix="doc_url_exception",
            expanded=False,
        )


def render_document_processing_tab():
    """
    渲染文档处理入口，支持本地上传和在线链接两种文档总结方式。
    """
    st.info("💡 二期已支持：本地 PDF / DOCX / TXT / Markdown / PPTX，以及在线 PDF 链接、网页文章链接。扫描版 PDF 会在提取不到文本时自动尝试 OCR。")
    st.caption("系统会先自动判断文档类型。只有识别为新闻、研究、时评、政策解读、行业分析等适合核查的文档，才会自动执行关键声明事实核查。")

    doc_source_upload, doc_source_url_tab = st.tabs(["📂 本地上传", "🔗 在线链接"])

    with doc_source_upload:
        st.caption("支持 PDF、DOCX、TXT、Markdown、PPTX，建议单文件不超过 20MB。")
        uploaded_doc = st.file_uploader(
            "上传文档",
            type=["pdf", "docx", "txt", "md", "markdown", "pptx"],
            key="doc_uploader",
            label_visibility="collapsed",
        )
        doc_col1, doc_col2 = st.columns([1, 2])
        with doc_col1:
            doc_sum_btn = st.button("📄 提取并总结文档", type="primary", use_container_width=True, key="btn_doc_sum")
        with doc_col2:
            st.caption("长文档会自动分块总结；事实核查只针对关键声明进行。")

        if doc_sum_btn:
            run_uploaded_document_summary(uploaded_doc)
        render_document_result("upload")

    with doc_source_url_tab:
        doc_url = st.text_input(
            "在线文档/文章链接",
            key="document_url_input",
            placeholder="https://example.com/report.pdf 或 https://example.com/article",
        )
        doc_url_col1, doc_url_col2 = st.columns([1, 2])
        with doc_url_col1:
            doc_url_btn = st.button("🌐 抓取并总结在线内容", type="primary", use_container_width=True, key="btn_doc_url_sum")
        with doc_url_col2:
            st.caption("支持在线 PDF、网页文章、公开 DOCX/PPTX/TXT/Markdown 链接。")

        if doc_url_btn:
            run_document_url_summary(doc_url)
        render_document_result("url")


def _append_subscription(channel_id, channel_name, channel_url, channel_avatar, channel_platform):
    """
    将频道写入订阅列表，并在存在重复时返回 False。
    """
    exists = any(sub["id"] == channel_id for sub in st.session_state.subscriptions)
    if exists:
        return False

    st.session_state.subscriptions.append({
        "id": channel_id,
        "name": channel_name,
        "url": channel_url,
        "avatar": channel_avatar,
        "added_at": datetime.now().isoformat(),
        "platform": channel_platform,
    })
    save_subscriptions(st.session_state.subscriptions)
    return True


def handle_subscription_search_or_add(new_channel_input):
    """
    处理订阅输入，支持直接添加频道链接或按关键词搜索频道。
    """
    if not new_channel_input:
        st.warning("请输入内容")
        return

    is_url = (
        "http" in new_channel_input
        or "://" in new_channel_input
        or new_channel_input.startswith("@")
        or "www." in new_channel_input
        or new_channel_input.startswith("BV")
    )

    if is_url:
        with st.spinner("正在获取频道信息..."):
            try:
                eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                cid, cname, curl, cavatar, cplatform = get_channel_info(
                    new_channel_input,
                    proxy_url=eff_proxy,
                    timeout_seconds=float(timeout),
                )
                if _append_subscription(cid, cname, curl, cavatar, cplatform):
                    st.success(f"已添加订阅: {cname} ({cplatform})")
                    st.rerun()
                st.warning(f"频道 '{cname}' 已在订阅列表中")
            except Exception as e:
                st.error(f"添加失败: {e}")
        return

    st.session_state.search_results = None
    with st.spinner(f"正在搜索 '{new_channel_input}' ..."):
        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
        results = search_channels(
            new_channel_input,
            limit=3,
            proxy_url=eff_proxy,
            timeout_seconds=float(timeout),
        )
        st.session_state.search_results = results
        if not results.get("youtube") and not results.get("bilibili"):
            st.warning("未找到相关频道")
        else:
            st.rerun()


def render_subscription_search_item(item):
    """
    渲染单个频道搜索结果，并支持一键加入订阅。
    """
    with st.container(border=True):
        c_avatar, c_info, c_btn = st.columns([1, 4, 1.5])
        with c_avatar:
            avatar = item.get("avatar")
            if avatar:
                if avatar.startswith("//"):
                    avatar = "https:" + avatar
                st.markdown(
                    f'<div style="display: flex; justify-content: center;">'
                    f'<img src="{avatar}" style="width: 100%; border-radius: 50%; aspect-ratio: 1/1; object-fit: cover;" referrerpolicy="no-referrer" />'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            elif item["platform"] == "youtube":
                st.markdown(
                    "<div style='height: 60px; display: flex; align-items: center; justify-content: center; font-size: 30px; background-color: #f0f0f0; border-radius: 50%;'>🟥</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='height: 60px; display: flex; align-items: center; justify-content: center; font-size: 30px; background-color: #f0f0f0; border-radius: 50%;'>🟦</div>",
                    unsafe_allow_html=True,
                )
        with c_info:
            name = item.get("name", "Unknown")
            desc = item.get("desc", "")
            url = item.get("url", "")
            st.markdown(f"**[{name}]({url})**")
            if desc:
                st.caption(desc)
            else:
                st.caption(f"{'YouTube' if item['platform'] == 'youtube' else 'Bilibili'} 频道")
        with c_btn:
            st.write("")
            if st.button("➕ 添加", key=f"add_res_{item['platform']}_{item['id']}", use_container_width=True):
                with st.spinner("正在添加..."):
                    try:
                        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                        cid, cname, curl, cavatar, cplatform = get_channel_info(
                            item["url"],
                            proxy_url=eff_proxy,
                            timeout_seconds=float(timeout),
                        )
                        if _append_subscription(cid, cname, curl, cavatar, cplatform):
                            st.session_state.search_results = None
                            st.success(f"已添加: {cname}")
                            st.rerun()
                        st.warning(f"已存在: {cname}")
                    except Exception as e:
                        st.error(f"添加失败: {e}")


def render_subscription_search_results():
    """
    渲染频道搜索结果列表。
    """
    if not st.session_state.get("search_results"):
        return

    st.divider()
    st.markdown("### 🔍 搜索结果")

    res_yt = st.session_state.search_results.get("youtube", [])
    res_b = st.session_state.search_results.get("bilibili", [])
    tab_res_yt, tab_res_b = st.tabs([f"YouTube ({len(res_yt)})", f"Bilibili ({len(res_b)})"])

    with tab_res_yt:
        if not res_yt:
            st.info("无结果")
        else:
            for item in res_yt:
                render_subscription_search_item(item)

    with tab_res_b:
        if not res_b:
            st.info("无结果")
        else:
            for item in res_b:
                render_subscription_search_item(item)

    if st.button("✕ 关闭搜索", key="close_search"):
        st.session_state.search_results = None
        st.rerun()


def split_subscriptions_by_platform():
    """
    将当前订阅按平台拆分为 YouTube 与 Bilibili 两组。
    """
    youtube_subscriptions = []
    bilibili_subscriptions = []

    for sub in st.session_state.subscriptions:
        platform = sub.get("platform")
        if not platform:
            sub_url = sub.get("url", "").lower()
            platform = "bilibili" if "bilibili.com" in sub_url else "youtube"

        if platform == "bilibili":
            bilibili_subscriptions.append(sub)
        else:
            youtube_subscriptions.append(sub)

    return youtube_subscriptions, bilibili_subscriptions


def render_subscription_card(sub, index_key_suffix, mode="grid"):
    """
    渲染单个订阅卡片，支持网格和列表两种视图。
    """
    real_index = st.session_state.subscriptions.index(sub)

    if mode == "grid":
        with st.container(border=True):
            c_mid = st.columns([1, 2, 1])
            with c_mid[1]:
                avatar_url = sub.get("avatar")
                if avatar_url:
                    if avatar_url.startswith("//"):
                        avatar_url = "https:" + avatar_url
                    st.markdown(
                        f'<div style="display: flex; justify-content: center;"><img src="{avatar_url}" style="width: 100%; border-radius: 50%; aspect-ratio: 1/1; object-fit: cover;" referrerpolicy="no-referrer" /></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='height: 80px; display: flex; align-items: center; justify-content: center; font-size: 40px;'>📺</div>",
                        unsafe_allow_html=True,
                    )
            name = sub["name"]
            if "马脸姐" in name:
                name = "马脸姐"
            if len(name) > 8:
                name = name[:7] + "..."
            st.markdown(
                f"<div style='text-align: center; font-weight: bold; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;' title='{sub['name']}'><a href='{sub['url']}' target='_blank' style='text-decoration: none; color: inherit;'>{name}</a></div>",
                unsafe_allow_html=True,
            )
            if st.button("🗑️", key=f"del_{real_index}_{index_key_suffix}", help=f"删除 {sub['name']}", use_container_width=True):
                st.session_state.subscriptions.pop(real_index)
                save_subscriptions(st.session_state.subscriptions)
                st.rerun()
        return

    c_av, c_nm, c_act = st.columns([1, 4, 1])
    with c_av:
        avatar_url = sub.get("avatar")
        if avatar_url:
            if avatar_url.startswith("//"):
                avatar_url = "https:" + avatar_url
            st.markdown(
                f'<div style="display: flex; align-items: center; height: 100%;"><img src="{avatar_url}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover;" referrerpolicy="no-referrer" /></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("📺")
    with c_nm:
        st.markdown(
            f"<div style='line-height: 32px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'><a href='{sub['url']}' target='_blank' style='text-decoration: none; color: inherit; font-weight: bold;'>{sub['name']}</a></div>",
            unsafe_allow_html=True,
        )
    with c_act:
        if st.button("🗑️", key=f"del_list_{real_index}_{index_key_suffix}", help=f"删除 {sub['name']}"):
            st.session_state.subscriptions.pop(real_index)
            save_subscriptions(st.session_state.subscriptions)
            st.rerun()
    st.divider()


def render_subscription_platform_section(title, subscriptions, index_key_suffix, view_mode):
    """
    渲染单个平台的订阅列表区域。
    """
    if not subscriptions:
        return

    st.markdown(title)
    if view_mode == "网格":
        cols_count = 4
        for i in range(0, len(subscriptions), cols_count):
            cols = st.columns(cols_count)
            for j in range(cols_count):
                if i + j < len(subscriptions):
                    with cols[j]:
                        render_subscription_card(subscriptions[i + j], index_key_suffix, mode="grid")
        return

    for sub in subscriptions:
        render_subscription_card(sub, index_key_suffix, mode="list")


def render_subscription_list_panel():
    """
    渲染已订阅频道列表。
    """
    st.divider()
    st.markdown("##### 📋 已订阅频道")
    view_mode = st.radio("视图模式", ["列表", "网格"], horizontal=True, index=0, key="sub_view_mode", label_visibility="collapsed")

    if not st.session_state.subscriptions:
        st.info("暂无订阅，请添加")
        return

    yt_subs, b_subs = split_subscriptions_by_platform()
    render_subscription_platform_section("#### 🟥 YouTube", yt_subs, "yt", view_mode)

    if b_subs and yt_subs:
        st.markdown("---")
    render_subscription_platform_section("#### 🟦 Bilibili", b_subs, "b", view_mode)


def render_subscription_management_panel():
    """
    渲染订阅管理面板，包含添加、搜索结果和订阅列表。
    """
    with st.expander("📺 订阅管理 (添加 / 查看 / 删除)", expanded=False):
        st.markdown("##### ➕ 添加新订阅")
        new_channel_input = st.text_input("输入频道链接或关键词 (如 '李永乐')", key="sub_input")

        col_act_1, col_act_2 = st.columns([1, 3])
        with col_act_1:
            if st.button("🔍 搜索 / 添加", use_container_width=True):
                handle_subscription_search_or_add(new_channel_input)

        render_subscription_search_results()
        render_subscription_list_panel()


def _resolve_subscription_platform_display(sub):
    """
    根据订阅信息返回平台标识与颜色，用于统一动态列表展示。
    """
    sub_platform = sub.get("platform", "")
    if not sub_platform:
        if "bilibili" in sub.get("url", "").lower():
            sub_platform = "bilibili"
        else:
            sub_platform = "youtube"

    if sub_platform == "bilibili":
        return "🟦 Bilibili", "blue"
    return "🟥 YouTube", "red"


def _check_subscription_recent_videos(sub, proxy, timeout_val):
    """
    检查单个订阅频道的最近视频更新。
    """
    try:
        min_dur = 0
        only_streams = False
        if sub["id"] == "UC8UCbiPrm2zN9nZHKdTevZA" or "王剑" in sub["name"] or "大康" in sub["name"]:
            min_dur = 1200
            # 这类频道既会发直播回放，也可能在 videos tab 发布更新。
            # 只扫 streams 会漏掉真正最新的内容，因此保留长视频过滤，但不再限制仅 streams。
            only_streams = False

        eff_timeout = min(float(timeout_val), 20.0)
        return sub["id"], get_channel_recent_videos(
            sub["url"],
            limit=5,
            proxy_url=proxy,
            timeout_seconds=eff_timeout,
            filter_longest=True,
            min_duration_seconds=min_dur,
            only_streams=only_streams,
        )
    except Exception as e:
        return sub["id"], e


def run_subscription_update_check():
    """
    执行全量订阅更新检查，并维护进度与结果状态。
    """
    if not st.session_state.subscriptions:
        st.info("暂无订阅频道，请先添加订阅后再检查更新。")
        st.session_state.is_updating_all = False
        return

    st.session_state.is_updating_all = True
    st.session_state.updates = {}

    with st.status("正在检查更新...", expanded=True) as status:
        progress_text = "准备开始：正在检测网络代理..."
        progress_bar = st.progress(0, text=progress_text)

        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
        progress_bar.progress(0, text="准备开始：正在初始化检查任务...")

        from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(len(st.session_state.subscriptions), 20)
    progress_bar.progress(0, text=f"正在启动 {max_workers} 个并发检查任务...")
    start_time = time.time()
    status.update(label="正在检查更新... (已耗时 0s)", state="running")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sub = {
            executor.submit(_check_subscription_recent_videos, sub, eff_proxy, timeout): sub
            for sub in st.session_state.subscriptions
        }

        completed_count = 0
        total_subs = len(st.session_state.subscriptions)
        progress_bar.progress(0.01, text=f"(0/{total_subs}) 任务已提交，等待结果...")

        for future in as_completed(future_to_sub):
            sub = future_to_sub[future]
            completed_count += 1
            pct = completed_count / total_subs

            elapsed = time.time() - start_time
            avg_time = elapsed / completed_count
            remain_count = total_subs - completed_count
            remain_time = avg_time * remain_count

            progress_bar.progress(
                pct,
                text=f"({completed_count}/{total_subs}) 正在检查: {sub['name']}... | 预计剩余: {int(remain_time)}s",
            )
            status.update(label=f"正在检查更新... (已耗时 {int(elapsed)}s)", state="running")

            try:
                sid, result = future.result()
                if isinstance(result, list):
                    if result:
                        st.session_state.updates[sid] = result
                        status.write(f"✅ {sub['name']}: 发现 {len(result)} 个新视频")
                else:
                    status.write(f"⚠️ {sub['name']} 检查失败: {result}")
            except Exception as exc:
                status.write(f"⚠️ {sub['name']} 异常: {exc}")

    total_elapsed = time.time() - start_time
    progress_bar.progress(1.0, text=f"检查完成！总耗时 {int(total_elapsed)}s")
    time.sleep(0.5)
    progress_bar.empty()
    status.update(label=f"✅ 更新检查完成 (耗时 {int(total_elapsed)}s)", state="complete", expanded=False)
    st.session_state.last_update_check = datetime.now().strftime("%H:%M")
    st.session_state.is_updating_all = False
    st.rerun()


def render_cached_subscription_summary(video_id):
    """
    渲染已缓存的订阅视频总结内容。
    """
    cache_key = f"cache_sum_{video_id}"
    if cache_key not in st.session_state:
        return False

    render_summary_content(
        st.session_state[cache_key],
        fact_title="🕵️ 新闻事实核查",
    )

    meta_key = f"cache_meta_{video_id}"
    if meta_key in st.session_state:
        st.divider()
        st.caption(st.session_state[meta_key])
    return True


def build_subscription_summary_footer(duration, whisper_device_info, transcript_text=""):
    """
    构建订阅视频总结页脚信息。
    """
    footer_str = f"本总结由 {pipeline_model_label} 流水线生成{whisper_device_info} | ⏳ 总耗时: {duration:.1f}s"

    try:
        raw_text = transcript_text or ""
        if "<!-- TIMING:" in raw_text:
            import re

            m_timing = re.search(r"<!-- TIMING: download=([\d\.]+), transcribe=([\d\.]+) -->", raw_text)
            if m_timing:
                dl_time = float(m_timing.group(1))
                tr_time = float(m_timing.group(2))
                footer_str += f" (📥 下载: {dl_time:.1f}s | 🎙️ 转写: {tr_time:.1f}s | 🤖 AI: {duration:.1f}s)"
    except Exception:
        pass

    return footer_str


def fetch_subscription_video_transcript(video_url, progress_bar):
    """
    抓取订阅视频字幕。
    """
    def update_progress(progress_value, progress_text):
        progress_bar.progress(progress_value, text=progress_text)

    text, err = internal_fetch_transcript(video_url, update_progress)
    if err:
        return "", err, ""

    _whisper_device_name, text = _extract_whisper_device_info(text)
    st.session_state.whisper_device_tag = ""
    return text, "", ""


def create_subscription_summary_stream(text):
    """
    创建订阅视频的流式总结请求。
    """
    from core_logic import summarize_text

    if summary_model_selected != fact_check_model_selected:
        return summarize_text(
            text,
            api_key,
            base_url,
            summary_model_selected,
            proxy_input,
            fact_check_model=fact_check_model_selected,
            stream=False,
        )

    return summarize_text(
        text,
        api_key,
        base_url,
        summary_model_selected,
        proxy_input,
        fact_check_model=fact_check_model_selected,
        stream=True,
    )


def stream_subscription_summary_response(stream, video_id, cache_key, start_time, whisper_device_info, transcript_text=""):
    """
    处理流式总结响应并写入缓存。
    """
    def stream_generator():
        full_response = ""

        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    content = delta.content
                    full_response += content
                    yield content

        end_time = time.time()
        duration = end_time - start_time
        footer_str = build_subscription_summary_footer(duration, whisper_device_info, transcript_text)

        st.session_state[f"cache_meta_{video_id}"] = footer_str

        is_valid_json = False
        try:
            if full_response.strip().startswith("{") and full_response.strip().endswith("}"):
                json.loads(full_response)
                is_valid_json = True
        except Exception:
            pass

        st.session_state[cache_key] = full_response

        if not is_valid_json:
            yield f"\n\n> {footer_str}"

    return stream_generator()


def render_subscription_video_summary_panel(video):
    """
    渲染单个视频的 AI 总结面板与流式生成逻辑。
    """
    with st.container(border=True):
        c_head_1, c_head_2 = st.columns([15, 1])
        with c_head_1:
            st.markdown("### 📝 AI 总结")
        with c_head_2:
            if st.button("✕", key=f"close_{video['id']}", help="关闭总结"):
                st.session_state.viewing_summaries.pop(video["id"])
                st.rerun()

        cache_key = f"cache_sum_{video['id']}"
        if render_cached_subscription_summary(video["id"]):
            return

        status_container = st.empty()
        progress_container = st.empty()
        progress_bar = progress_container.progress(0, text="⏳ 正在初始化...")
        start_time = time.time()
        progress_bar.progress(10, text="⏳ 正在准备抓取字幕/转写音频 (可能需要下载音频)...")

        try:
            text, err, whisper_device_info = fetch_subscription_video_transcript(video["url"], progress_bar)
            if err:
                progress_container.empty()
                status_container.error(f"❌ 字幕获取失败: {err}")
                return

            progress_bar.progress(40, text="🚀 字幕获取成功，正在请求 AI 生成总结...")
            if summary_model_selected != fact_check_model_selected:
                status_container.info("🚀 正在请求 AI 生成总结（双模型流水线）...")
            else:
                status_container.info("🚀 正在请求 AI 生成总结 (流式输出)...")

            if not api_key:
                progress_container.empty()
                status_container.error("请在侧边栏填写 API Key")
                return

            try:
                progress_bar.progress(50, text="🚀 正在连接大模型 API...")
                stream = create_subscription_summary_stream(text)

                progress_bar.progress(60, text="🚀 开始接收 AI 响应...")
                time.sleep(0.2)
                progress_container.empty()

                if isinstance(stream, str):
                    if stream.strip().startswith("{"):
                        end_time = time.time()
                        duration = end_time - start_time
                        st.session_state[cache_key] = stream
                        st.session_state[f"cache_meta_{video['id']}"] = build_subscription_summary_footer(duration, whisper_device_info, text)
                        status_container.empty()
                        st.rerun()
                    status_container.error(stream)
                    return

                st.write_stream(
                    stream_subscription_summary_response(
                        stream,
                        video["id"],
                        cache_key,
                        start_time,
                        whisper_device_info,
                        text,
                    )
                )
                status_container.empty()
                st.rerun()

            except Exception as e:
                progress_container.empty()
                status_container.error(f"总结过程出错: {e}")
        except Exception as outer_e:
            progress_container.empty()
            status_container.error(f"处理出错: {outer_e}")


def format_subscription_video_meta(video):
    """
    格式化订阅视频的发布时间与时长信息。
    """
    info_parts = []
    upload_date = video.get("upload_date")
    duration = video.get("duration")

    if upload_date:
        date_text = str(upload_date)
        if len(date_text) == 8:
            info_parts.append(f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}")
        else:
            info_parts.append(date_text)

    if duration:
        if duration >= 3600:
            duration_text = f"{int(duration // 3600)}小时{int((duration % 3600) // 60)}分"
        else:
            duration_text = f"{int(duration // 60)}分{int(duration % 60)}秒"
        info_parts.append(f"⏳ {duration_text}")

    return " | ".join(info_parts)


def ensure_subscription_summary_state():
    """
    确保订阅视频总结状态容器已初始化。
    """
    if "viewing_summaries" not in st.session_state:
        st.session_state.viewing_summaries = {}


def render_subscription_video_item(video):
    """
    渲染单个更新视频卡片，并在需要时展示对应总结面板。
    """
    with st.container(border=True):
        c1, c2 = st.columns([5, 1])

        with c1:
            st.markdown(f"##### [{video['title']}]({video['url']})")
            st.caption(format_subscription_video_meta(video))

        with c2:
            st.write("")
            ensure_subscription_summary_state()

            if st.button("✨ 总结", key=f"btn_sum_{video['id']}", use_container_width=True):
                st.session_state.viewing_summaries[video["id"]] = True
                st.rerun()

    if st.session_state.get("viewing_summaries", {}).get(video["id"]):
        render_subscription_video_summary_panel(video)


def render_subscription_channel_updates(sub, videos):
    """
    渲染单个订阅频道的更新列表。
    """
    p_badge, p_color = _resolve_subscription_platform_display(sub)
    st.markdown("---")
    st.markdown(f"#### [{sub['name']}]({sub['url']}) :{p_color}[{p_badge}]")

    for video in videos:
        render_subscription_video_item(video)


def render_subscription_updates_results():
    """
    渲染更新检查后的频道结果列表。
    """
    if st.session_state.updates:
        for sub in st.session_state.subscriptions:
            sid = sub["id"]
            if sid not in st.session_state.updates:
                continue

            videos = st.session_state.updates[sid]
            if not videos:
                continue

            render_subscription_channel_updates(sub, videos)
        return

    if "last_update_check" in st.session_state:
        st.info(f"检查完成 ({st.session_state.last_update_check})，暂无新内容")
    else:
        st.info("点击上方按钮检查更新")


def render_subscription_updates_panel():
    """
    渲染订阅更新检查与最新动态列表。
    """
    with st.container():
        st.subheader("🆕 最新动态")

        if st.button("🔄 检查所有订阅更新", type="primary", use_container_width=True):
            run_subscription_update_check()

        update_container = st.empty()

        if not st.session_state.get("is_updating_all", False):
            with update_container.container():
                render_subscription_updates_results()


def render_subscription_dynamic_tab():
    """
    渲染订阅管理与最新动态区域。
    """
    render_subscription_management_panel()
    render_subscription_updates_panel()


def render_daily_report_filters(daily_items):
    """
    渲染日报筛选栏，并返回筛选条件。
    """
    dates = [item.get("date") for item in daily_items if item.get("date")]
    today_key = _now().strftime("%Y-%m-%d")
    default_index = dates.index(today_key) if today_key in dates else 0

    filter_c1, filter_c2, filter_c3 = st.columns([2, 1, 2])
    with filter_c1:
        selected_date = st.selectbox("选择日期", dates, index=default_index, label_visibility="collapsed")
    with filter_c2:
        status_filter = st.selectbox("状态筛选", ["全部", "成功", "失败"], index=0, label_visibility="collapsed")
    with filter_c3:
        keyword = st.text_input("搜索标题", value="", placeholder="🔍 搜索更新内容...", label_visibility="collapsed")

    return selected_date, status_filter, keyword


def render_daily_report_metrics(day_info):
    """
    渲染选中日期的日报统计信息。
    """
    if not day_info:
        return

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("总计更新", day_info.get("total_items"))
    metric_2.metric("成功", day_info.get("success_items"))
    metric_3.metric("失败", day_info.get("failed_items"))


def filter_daily_report_items(items, status_filter, keyword):
    """
    根据状态与关键词过滤日报条目。
    """
    filtered_items = []
    items_sorted = sorted(items, key=lambda item: item.get("created_at") or "", reverse=True)
    keyword_text = keyword.strip().lower() if keyword else ""

    for item in items_sorted:
        status = item.get("status") or ""
        if status_filter == "成功" and status != "success":
            continue
        if status_filter == "失败" and status == "success":
            continue

        title = item.get("title") or "未命名内容"
        if keyword_text and keyword_text not in title.lower():
            continue
        filtered_items.append(item)

    return filtered_items


def render_daily_report_item(item):
    """
    渲染单条日报记录卡片。
    """
    status = item.get("status") or ""
    title = item.get("title") or "未命名内容"

    with st.container(border=True):
        head_c1, head_c2 = st.columns([4, 1])
        with head_c1:
            st.markdown(f"**{title}**")
            caption_parts = []
            if item.get("channel_name"):
                caption_parts.append(f"📺 {item.get('channel_name')}")
            if item.get("created_at"):
                time_str = _parse_iso(item.get("created_at")).strftime("%H:%M")
                caption_parts.append(f"🕒 {time_str}")
            st.caption(" | ".join(caption_parts))
        with head_c2:
            if status == "success":
                st.success("成功", icon="✅")
            else:
                st.error("失败", icon="❌")

        if item.get("url"):
            st.caption(f"🔗 [视频链接]({item.get('url')})")

        if status == "success":
            with st.expander("查看 AI 总结", expanded=False):
                render_summary_content(
                    item.get("summary") or "",
                    fact_title="🕵️ 新闻事实核查",
                )
        else:
            err_text = item.get("error") or "未知错误"
            st.error(f"失败原因: {err_text}")


def render_daily_report_tab(run_items):
    """
    渲染每日简报子页。
    """
    daily_items, items_by_day = _group_items_by_day(run_items)
    if not daily_items:
        st.info("暂无更新记录，请先在“任务管理”中添加并执行任务")
        return

    selected_date, status_filter, keyword = render_daily_report_filters(daily_items)
    day_info = next((item for item in daily_items if item.get("date") == selected_date), None)
    render_daily_report_metrics(day_info)

    st.divider()
    items = items_by_day.get(selected_date, [])
    if not items:
        st.caption("该日期暂无更新内容")
        return

    filtered_items = filter_daily_report_items(items, status_filter, keyword)
    if not filtered_items:
        st.caption("没有符合当前筛选条件的更新内容")
        return

    for item in filtered_items:
        render_daily_report_item(item)


def render_task_quick_actions(settings, tasks, runs, run_items, processed_ids):
    """
    渲染任务管理中的快捷操作区域。
    """
    st.markdown("##### 🚀 快捷操作")
    if not tasks:
        st.caption("暂无可执行任务")
        return

    if st.button("立即执行全部", type="primary", use_container_width=True):
        with st.spinner("正在执行全部任务..."):
            for task in tasks:
                if not task.get("enabled"):
                    continue
                settings = _run_task_once(task, settings)

            runs = settings.get("scheduled_runs") or runs
            run_items = settings.get("scheduled_run_items") or run_items
            processed_ids = settings.get("scheduled_processed_ids") or processed_ids
            _save_scheduled_state(settings, tasks, settings.get("schedule_logs") or [], runs, run_items, processed_ids)

        st.toast("已执行全部启用任务", icon="✅")
        st.rerun()


def _get_subscription_platform_label(url):
    """
    根据频道 URL 返回平台展示名。
    """
    if not url:
        return "❓"
    if "youtube" in url or "youtu.be" in url:
        return "YouTube"
    if "bilibili" in url:
        return "Bilibili"
    return "❓"


def build_task_subscription_label_map(subs):
    """
    为任务创建弹层构建频道标签到订阅对象的映射。
    """
    label_map = {}
    for sub in subs:
        platform = sub.get("platform")
        if not platform or platform == "?":
            platform = _get_subscription_platform_label(sub.get("url"))
        label = f"{sub.get('name')} ({platform})"
        label_map[label] = sub
    return label_map


def render_task_schedule_inputs():
    """
    渲染任务调度配置输入，并返回统一的配置结果。
    """
    st.divider()
    st.caption("⏰ 时间设置")
    simple_mode = st.toggle("简单模式", value=True)

    interval_hours = 0
    cron_value = ""
    weekdays_value = []
    schedule_time = None

    if simple_mode:
        schedule_type = "每天"
        schedule_time = st.time_input("每天几点运行", value=dt_time(9, 0))
    else:
        schedule_type = st.selectbox("周期类型", ["每天", "每周", "间隔小时", "Cron"])
        if schedule_type == "每天":
            schedule_time = st.time_input("时间点", value=dt_time(9, 0))
        elif schedule_type == "每周":
            schedule_time = st.time_input("时间点", value=dt_time(9, 0))
            selected_days = st.multiselect("星期", ["一", "二", "三", "四", "五", "六", "日"], default=["一", "二", "三", "四", "五"])
            weekdays_value = [["一", "二", "三", "四", "五", "六", "日"].index(day) for day in selected_days]
        elif schedule_type == "间隔小时":
            interval_hours = st.number_input("每隔几小时", 1, 168, 6)
        else:
            cron_value = st.text_input("Cron表达式", "0 9 * * *")

    return {
        "schedule_type": schedule_type,
        "schedule_time": schedule_time,
        "weekdays_value": weekdays_value,
        "interval_hours": interval_hours,
        "cron_value": cron_value,
    }


def normalize_schedule_type_label(schedule_type_label):
    """
    将任务创建弹层中的中文调度类型转换为内部标识。
    """
    if schedule_type_label == "每天":
        return "daily"
    if schedule_type_label == "每周":
        return "weekly"
    if schedule_type_label == "间隔小时":
        return "interval"
    return "cron"


def build_scheduled_task_from_subscription(sub, schedule_config):
    """
    根据订阅信息和调度配置构造标准任务对象。
    """
    new_task = _normalize_task({
        "channel_id": sub.get("id"),
        "channel_name": sub.get("name"),
        "channel_url": sub.get("url"),
        "platform": sub.get("platform"),
        "schedule_type": normalize_schedule_type_label(schedule_config["schedule_type"]),
        "time": schedule_config["schedule_time"].strftime("%H:%M") if schedule_config["schedule_time"] else "09:00",
        "weekdays": schedule_config["weekdays_value"],
        "interval_hours": schedule_config["interval_hours"],
        "cron": schedule_config["cron_value"],
        "enabled": True,
        "max_items": 5,
        "min_duration_seconds": 0,
        "only_streams": False,
    })
    next_run = _compute_next_run(new_task, _now())
    new_task["next_run_at"] = _iso(next_run) if next_run else ""
    return new_task


def render_task_creation_popover(settings, tasks, logs, runs, run_items, processed_ids):
    """
    渲染新建任务弹层。
    """
    st.markdown("##### ➕ 新建任务")
    with st.popover("添加新任务", use_container_width=True):
        if not st.session_state.subscriptions:
            st.warning("请先在“频道订阅”中添加频道")
            return

        subs = st.session_state.subscriptions
        label_map = build_task_subscription_label_map(subs)

        keyword = st.text_input("搜索频道", placeholder="输入关键词...", label_visibility="collapsed")
        filtered_labels = [label for label in label_map.keys() if keyword.lower() in label.lower()] if keyword else list(label_map.keys())

        if st.button("全选", use_container_width=True):
            st.session_state.selected_channel_labels = filtered_labels
            st.rerun()

        if "selected_channel_labels" not in st.session_state:
            st.session_state.selected_channel_labels = []

        selected_labels = st.multiselect("选择频道", filtered_labels, default=st.session_state.selected_channel_labels)
        st.session_state.selected_channel_labels = selected_labels

        schedule_config = render_task_schedule_inputs()

        if st.button("创建任务", type="primary", use_container_width=True):
            if not selected_labels:
                st.error("请选择频道")
                return

            added_count = 0
            for label in selected_labels:
                sub = label_map[label]
                new_task = build_scheduled_task_from_subscription(sub, schedule_config)
                if _task_conflict(tasks, new_task):
                    continue

                tasks.append(new_task)
                added_count += 1

            _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
            if added_count > 0:
                st.success(f"已创建 {added_count} 个任务")
                st.rerun()
            st.warning("未创建任务（可能已存在）")


def ensure_task_next_runs(settings, tasks, logs, runs, run_items, processed_ids):
    """
    为缺失下次执行时间的启用任务补齐 next_run_at。
    """
    updated = False
    for task in tasks:
        if task.get("enabled") and not task.get("next_run_at"):
            computed = _compute_next_run(task, _now())
            task["next_run_at"] = _iso(computed) if computed else ""
            updated = True

    if updated:
        _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)


def render_task_list_item(task, settings, tasks, logs, runs, run_items, processed_ids):
    """
    渲染单个任务卡片。
    """
    next_run = _parse_iso(task.get("next_run_at"))
    is_enabled = task.get("enabled")

    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            st.markdown(f"**{task.get('channel_name')}**")
            st.caption(f"{_format_schedule_label(task)}")
        with c2:
            st.caption(f"下次: {next_run.strftime('%m-%d %H:%M') if next_run else '-'}")
            if task.get("last_error"):
                st.caption(f":red[{task.get('last_error')[:10]}...]")
        with c3:
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("停用" if is_enabled else "启用", key=f"tg_{task['id']}"):
                    task["enabled"] = not task["enabled"]
                    _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                    st.rerun()
            with col_btn2:
                if st.button("🗑️", key=f"del_{task['id']}", help="删除任务"):
                    tasks[:] = [item for item in tasks if item["id"] != task["id"]]
                    _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                    st.rerun()


def render_task_list_panel(settings, tasks, logs, runs, run_items, processed_ids):
    """
    渲染任务列表区域。
    """
    st.divider()
    st.markdown("##### 📝 任务列表")
    if not tasks:
        st.info("暂无任务")
        return

    ensure_task_next_runs(settings, tasks, logs, runs, run_items, processed_ids)
    for task in tasks:
        render_task_list_item(task, settings, tasks, logs, runs, run_items, processed_ids)


def render_task_management_tab(settings, tasks, logs, runs, run_items, processed_ids):
    """
    渲染任务管理子页。
    """
    col_quick, col_create = st.columns([1, 2])
    with col_quick:
        render_task_quick_actions(settings, tasks, runs, run_items, processed_ids)

    with col_create:
        render_task_creation_popover(settings, tasks, logs, runs, run_items, processed_ids)

    render_task_list_panel(settings, tasks, logs, runs, run_items, processed_ids)


def render_automation_rules_tab():
    """
    渲染自动规则、日报和任务管理区域。
    """
    _start_scheduler_once()
    settings, tasks, logs, runs, run_items, processed_ids = _load_scheduled_state()
    settings["timeout_seconds"] = float(settings.get("timeout_seconds") or 20.0)

    sub_tab_report, sub_tab_manage = st.tabs(["📅 每日简报", "⚙️ 任务管理"])

    with sub_tab_report:
        render_daily_report_tab(run_items)

    with sub_tab_manage:
        render_task_management_tab(settings, tasks, logs, runs, run_items, processed_ids)


def render_processing_center_page(current_bg_task_status):
    """
    渲染处理中心页面壳，统一组织视频、文本和文档三个入口。
    """
    st.markdown("### 🧭 处理中心")
    st.caption("把原来的单视频处理、粘贴字幕、文档总结合并到一个工作台，统一输入、统一处理、统一查看结果。")
    if current_bg_task_status and current_bg_task_status.get("status") in ["queued", "running"]:
        st.warning("当前有后台任务正在运行。你仍然可以浏览页面，但建议等待当前任务完成后再发起新的抓取请求。")

    if st.session_state.prefer_paste_tab:
        processing_tab_paste, processing_tab_video, processing_tab_doc = st.tabs(["✍️ 粘贴文本", "🎬 视频链接", "📄 上传文档"])
    else:
        processing_tab_video, processing_tab_paste, processing_tab_doc = st.tabs(["🎬 视频链接", "✍️ 粘贴文本", "📄 上传文档"])

    with processing_tab_video:
        render_video_processing_tab()

    with processing_tab_paste:
        render_text_processing_tab()

    with processing_tab_doc:
        render_document_processing_tab()


def render_automation_page():
    """
    渲染订阅自动化页面壳，统一组织订阅动态与规则日报。
    """
    st.markdown("### 📡 订阅自动化")
    st.caption("把频道订阅、更新检查和定时执行放到同一个页面中，统一管理自动化能力。")
    automation_tab_subs, automation_tab_rules = st.tabs(["📺 订阅与动态", "⏰ 规则与日报"])

    with automation_tab_subs:
        render_subscription_dynamic_tab()

    with automation_tab_rules:
        render_automation_rules_tab()


current_bg_task_id, current_bg_task_status = render_background_task_status_panel()


# ==========================
# 处理中心：统一视频 / 文本 / 文档三种输入方式
# ==========================
with tab_processing:
    render_processing_center_page(current_bg_task_status)


# ==========================
# 任务中心
# ==========================
with tab_tasks:
    task_status_value, task_logs, task_runs, task_run_items = render_task_center_page(
        current_bg_task_id,
        current_bg_task_status,
    )


# ==========================
# 订阅自动化
# ==========================
with tab_automation:
    render_automation_page()

# ==========================
# 内容资产库
# ==========================
with tab_library:
    render_library_page()

# ==========================
# 设置与诊断
# ==========================
with tab_settings:
    render_settings_diagnostics_page(task_status_value, task_logs, task_runs, task_run_items)
