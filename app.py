
import streamlit as st
import threading
import time
import traceback
import json
import os
import re
import uuid
import calendar
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
    fetch_available_models,
    get_channel_info,
    get_channel_recent_videos,
    search_channels,
    get_remote_worker_status,
)

# --- 常量定义 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "subscriptions.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
GUESTBOOK_FILE = os.path.join(BASE_DIR, "guestbook.json")

@st.cache_resource
def _get_shared_lock():
    return threading.Lock()

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

def load_history():
    return load_json_file(HISTORY_FILE, [])

def save_history(history):
    save_json_file(HISTORY_FILE, history)

def load_guestbook():
    return load_json_file(GUESTBOOK_FILE, [])

def save_guestbook(guestbook):
    save_json_file(GUESTBOOK_FILE, guestbook)


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
    model_name = settings.get("model") or "gpt-3.5-turbo"
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
        "model": model_name,
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
                summary = summarize_text(text, api_key, base_url, model_name, eff_proxy)
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
if "proxy" not in st.session_state:
    st.session_state.proxy = st.session_state.settings.get("proxy", "")
if "transcript_text" not in st.session_state:
    st.session_state.transcript_text = ""
if "summary_text" not in st.session_state:
    st.session_state.summary_text = ""
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
        "proxy": st.session_state.settings.get("proxy", ""),
        "remember_api_key": remember_api_key_initial,
    }

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

asr_enabled = True
asr_model = os.environ.get("ASR_MODEL", "base")
asr_fast_mode = True

api_key = os.environ.get("OPENAI_API_KEY", st.session_state.settings.get("api_key", ""))
base_url = os.environ.get("OPENAI_BASE_URL", st.session_state.settings.get("base_url", "https://api.openai.com/v1"))
model_selected = os.environ.get("OPENAI_MODEL", st.session_state.settings.get("model", "gpt-3.5-turbo"))

st.session_state.proxy = proxy_input
st.session_state.api_key = api_key
st.session_state.base_url = base_url
st.session_state.model = model_selected



# --- 主界面 ---
st.title("🎬 Video Summarizer")
st.caption("本地运行的视频字幕抓取与 AI 总结工具 | 支持 YouTube & Bilibili | yt-dlp & Whisper")

# 使用 Tabs 分割功能
tab_single, tab_doc, tab_sub, tab_batch, tab_history, tab_guestbook = st.tabs(["🎬 单视频处理", "📄 文档总结", "📡 频道订阅", "⏰ 定时任务", "📜 历史记录", "💬 留言板"])

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
        # 注入私有属性
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
            fast_tag = " + 极速" if asr_fast_mode else ""
            progress_callback(30, f"获取字幕/音频 (Whisper: {asr_model}{fast_tag})...")
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

def internal_summarize(text, model_name, api_key_override=None, base_url_override=None, proxy_override=None):
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
            summary = summarize_text(
                text,
                eff_api_key,
                eff_base_url,
                model_name,
                eff_proxy,
                stream=False  # 后台任务默认不使用流式
            )
            return summary, None
        except Exception as e:
            return None, str(e)


def internal_summarize_document(file_name, file_bytes, model_name, progress_callback=None, api_key_override=None, base_url_override=None, proxy_override=None):
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = proxy_override or proxy_input

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

        def relay_document_progress(pct, message):
            if progress_callback:
                progress_callback(25 + int(min(max(pct, 0), 100) * 0.45), message)

        summary_result = summarize_document_text(
            extracted["clean_text"],
            eff_api_key,
            eff_base_url,
            model_name,
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
            model=model_name,
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
                model=model_name,
                proxy_url=eff_proxy,
                max_claims=int(fact_check_plan.get("recommended_claim_count") or 5),
                progress_callback=relay_fact_progress,
            )
        return {
            "extract": extracted,
            "summary": summary_result,
            "fact_check_markdown": fact_check_markdown,
            "fact_check_plan": fact_check_plan,
        }, None


def internal_summarize_document_url(source_url, model_name, progress_callback=None, api_key_override=None, base_url_override=None, proxy_override=None):
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = proxy_override or proxy_input

        if not eff_api_key:
            return None, "请先填写 API Key。"
        if progress_callback:
            progress_callback(10, "正在抓取在线文档/网页...")

        extracted = extract_document_from_url(source_url, proxy_url=eff_proxy)
        if progress_callback:
            progress_callback(25, f"在线内容解析完成，正文约 {extracted['char_count']} 字符。")

        def relay_document_progress(pct, message):
            if progress_callback:
                progress_callback(25 + int(min(max(pct, 0), 100) * 0.45), message)

        summary_result = summarize_document_text(
            extracted["clean_text"],
            eff_api_key,
            eff_base_url,
            model_name,
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
            model=model_name,
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
                model=model_name,
                proxy_url=eff_proxy,
                max_claims=int(fact_check_plan.get("recommended_claim_count") or 5),
                progress_callback=relay_fact_progress,
            )
        return {
            "extract": extracted,
            "summary": summary_result,
            "fact_check_markdown": fact_check_markdown,
            "fact_check_plan": fact_check_plan,
        }, None


# ==========================
# ====== 新增：后台任务状态轮询 ======
# ==========================
import time
from task_runner import submit_task, get_task_status

if "bg_task_id" not in st.session_state:
    st.session_state.bg_task_id = None

# 如果有后台任务正在跑，展示进度条并自动刷新
if st.session_state.bg_task_id:
    task_id = st.session_state.bg_task_id
    status_info = get_task_status(task_id)
    
    st.info(f"⏳ 后台任务进行中... (ID: {task_id[:8]})")
    status_col1, status_col2 = st.columns([3, 1])
    
    with status_col1:
        if status_info["status"] == "queued":
            st.warning("🔄 任务排队中...")
        elif status_info["status"] == "running":
            with st.spinner("🚀 正在抓取和总结中，请稍候..."):
                time.sleep(2)  # 给前端一点喘息时间
        elif status_info["status"] == "success":
            st.success("✅ 任务完成！")
            st.markdown("### 总结结果")
            st.write(status_info.get("result", "无内容返回"))
            # 完成后清空 task_id 允许提交新任务
            if st.button("清理状态并开启新任务"):
                st.session_state.bg_task_id = None
                st.rerun()
        elif status_info["status"] == "failed":
            st.error(f"❌ 任务失败: {status_info.get('error', '未知错误')}")
            if st.button("清理状态并重试"):
                st.session_state.bg_task_id = None
                st.rerun()
    
    with status_col2:
        if status_info["status"] in ["queued", "running"]:
            if st.button("刷新进度"):
                st.rerun()
                
    # 只要还在跑，就自动触发重新执行页面（模拟轮询）
    if status_info["status"] in ["queued", "running"]:
        time.sleep(3)
        st.rerun()
        
    # 如果有后台任务在跑，就不要展示下面的输入框了，避免冲突
    st.stop()
# ====== 新增结束 ======

# ==========================
# Tab 1: 单视频处理
# ==========================
with tab_single:
    # --- 界面布局 ---
    st.info("💡 支持输入：\n- YouTube 视频链接 / ID\n- Bilibili 视频链接 / BV号")
    status_col1, status_col2 = st.columns([5, 1])
    with status_col2:
        remote_status_refresh = st.button("刷新节点状态", key="btn_refresh_remote_status", use_container_width=True)
    remote_status = get_remote_worker_status_cached(1 if remote_status_refresh else 0)
    with status_col1:
        if remote_status.get("configured"):
            host = str(remote_status.get("worker_host") or "unknown")
            mode = str(remote_status.get("remote_mode") or "disabled")
            fallback_disabled = bool(remote_status.get("disable_render_asr_fallback"))
            if remote_status.get("health_ok"):
                st.success(
                    f"本地抓取节点在线 | mode={mode} | host={host} | "
                    f"Render ASR兜底={'关闭' if fallback_disabled else '开启'}"
                )
            else:
                err = str(remote_status.get("health_error") or "unknown")
                st.error(
                    f"本地抓取节点异常 | mode={mode} | host={host} | "
                    f"Render ASR兜底={'关闭' if fallback_disabled else '开启'} | 错误: {err}"
                )
            with st.expander("查看抓取节点状态详情", expanded=False):
                st.code(json.dumps(remote_status, ensure_ascii=False, indent=2))
        else:
            st.warning("未配置本地抓取节点。当前只能依赖 Render 自己抓取/转写，低内存环境下更容易失败。")
    url = st.text_input("视频链接或 ID", value=st.session_state.get("input_url", ""), placeholder="https://www.youtube.com/watch?v=... 或 https://www.bilibili.com/video/BV...")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        fetch_btn = st.button("🚀 一键抓取并总结", type="primary", use_container_width=True, key="btn_single_fetch")
        # --- 新增后台任务提交按钮 ---
        bg_fetch_btn = st.button("后台异步处理 (防超时)", type="secondary", use_container_width=True)
    with col2:
        summary_btn = st.button("🤖 仅重新生成总结", use_container_width=True, key="btn_single_sum")
    with col3:
        check_btn = st.button("🔍 检测可用字幕", use_container_width=True, key="btn_single_check")

    # --- 新增异步任务触发逻辑 ---
    if bg_fetch_btn:
        if not url:
            st.warning("请输入视频链接")
        else:
            task_id = submit_task(url, model_selected, proxy_input, use_system_proxy, api_key, base_url)
            st.session_state.bg_task_id = task_id
            st.rerun()

    def do_fetch_single():
        if not url:
            st.warning("请输入视频链接")
            return

        status_container = st.empty()
        status_container.info("正在初始化...")
        
        try:
            # 网络预检
            with st.status("🔍 网络预检中...", expanded=False) as status:
                eff_proxy, pac_note = get_effective_proxy(proxy_input, use_system_proxy)
                status.write(f"当前代理: {eff_proxy or '无 (直连)'}")
                if pac_note: status.info(pac_note)
                
                net_err = check_network(eff_proxy, timeout=5.0)
                if net_err:
                    status.update(label="⚠️ 网络预检失败", state="error", expanded=True)
                    st.warning(f"无法连接 Google/YouTube。\n错误信息：{net_err}")
                else:
                    status.update(label="✅ 网络预检通过", state="complete")
            
            # 抓取字幕
            status_container.info("正在抓取字幕/转写音频...")
            progress_bar = st.progress(0)
            
            # 计时开始
            t_start_all = time.time()
            
            used_asr = False
            asr_notice_shown = False
            def update_progress(p, t):
                nonlocal used_asr, asr_notice_shown
                progress_bar.progress(p, text=t)
                if (not asr_notice_shown) and ("Whisper" in str(t) or "whisper" in str(t)):
                    status_container.warning("⚠️ 字幕未获取成功，已自动切换到音频转写，耗时可能较长...")
                    asr_notice_shown = True
                    used_asr = True
                
            text, err = internal_fetch_transcript(url, update_progress)
            
            # 抓取阶段耗时
            t_fetch_end = time.time()
            fetch_duration = t_fetch_end - t_start_all
            
            if err:
                progress_bar.empty()
                status_container.error("❌ 抓取失败")
                st.error(err)
                return

            whisper_device_info, text = _extract_whisper_device_info(text)
            st.session_state.whisper_device_tag = whisper_device_info

            st.session_state.transcript_text = text

            if used_asr:
                msg = f"🎉 音频转写完成！(Whisper: {whisper_device_info or 'CPU'}) | 耗时: {fetch_duration:.1f}s"
                status_container.success(msg)
            else:
                msg = f"🎉 成功获取字幕！ | 耗时: {fetch_duration:.1f}s"
                status_container.success(msg)
                
            time.sleep(0.5)
            progress_bar.empty()
            
            # 自动总结
            do_summary_single(manual=False, fetch_duration=fetch_duration)
                
        except Exception as e:
            status_container.error("❌ 执行异常")
            st.error(f"{e}")
            st.code(traceback.format_exc())

    def do_summary_single(manual=True, fetch_duration=0.0):
        if not st.session_state.transcript_text:
            if manual: st.warning("请先抓取字幕")
            return
        
        t_sum_start = time.time()
        with st.spinner(f"正在请求 AI 总结 ({model_selected})..."):
            summary, err = internal_summarize(st.session_state.transcript_text, model_selected)
            
            t_sum_end = time.time()
            sum_duration = t_sum_end - t_sum_start
            total_duration = fetch_duration + sum_duration
            
            # 保存耗时信息到 session_state
            st.session_state.summary_duration = {
                "fetch": fetch_duration,
                "summary": sum_duration,
                "total": total_duration
            }
            
            if err:
                st.error(f"总结失败: {err}")
            else:
                st.session_state.summary_text = summary
                if manual: 
                    st.success(f"总结完成 | AI生成耗时: {sum_duration:.1f}s")
                
                # 自动保存到历史记录
                try:
                    add_history_entry("single", url, summary, st.session_state.transcript_text)
                except Exception as e_hist:
                    print(f"Failed to save history: {e_hist}")

    def do_check_single():
        if not url: return
        try:
            with st.spinner("检测中..."):
                video_id, _, _ = get_transcript_from_input(url, languages)
                api = build_api(proxy_input, float(timeout), use_system_proxy, int(retries))
                report = list_available_transcripts(api, video_id)
                st.text(report)
        except Exception as e:
            st.error(format_error(e))

    if fetch_btn:
        do_fetch_single()
    if summary_btn:
        do_summary_single()
    if check_btn:
        do_check_single()

    if st.session_state.summary_text:
        st.markdown("### 📝 AI 总结")
        
        # 显示总结耗时统计（如果有）
        if "summary_duration" in st.session_state and st.session_state.summary_duration:
            dur = st.session_state.summary_duration
            fetch_t = dur.get("fetch", 0)
            sum_t = dur.get("summary", 0)
            total_t = dur.get("total", 0)
            
            # 使用 metric 样式或自定义 badge
            st.caption(f"⏱️ **总耗时: {total_t:.1f}s** (抓取/转写: {fetch_t:.1f}s | AI 生成: {sum_t:.1f}s)")
            
        # 尝试解析 JSON 总结并分栏显示
        summary_content = st.session_state.summary_text
        summary_md, fact_check_md = _parse_summary_for_ui(summary_content)
        if summary_md:
            col_sum, col_check = st.columns([1.2, 1])
            with col_sum:
                st.markdown(summary_md)
            with col_check:
                st.info("🕵️ **新闻事实核查**")
                if fact_check_md:
                    st.markdown(fact_check_md)
                else:
                    st.warning("⚠️ 本次未成功拆出结构化事实核查结果。")
        else:
            # 兼容旧的纯文本总结
            st.markdown(summary_content)

        st.divider()
        
        # 尝试提取 fetch/download 耗时
        footer_info = ""
        if st.session_state.whisper_device_tag:
             footer_info = f"⚡ Whisper: {st.session_state.whisper_device_tag}"
        
        try:
            # 检查 transcript_text 是否包含 TIMING tag
            raw_text = st.session_state.transcript_text or ""
            if "<!-- TIMING:" in raw_text:
                import re
                m_timing = re.search(r"<!-- TIMING: download=([\d\.]+), transcribe=([\d\.]+) -->", raw_text)
                if m_timing:
                    dl_time = float(m_timing.group(1))
                    tr_time = float(m_timing.group(2))
                    if footer_info: footer_info += " | "
                    footer_info += f"📥 下载: {dl_time:.1f}s | 🎙️ 转写: {tr_time:.1f}s"
        except Exception:
            pass
            
        if footer_info:
            st.caption(footer_info)

    if st.session_state.transcript_text:
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


# ==========================
# Tab 2: 文档总结
# ==========================
with tab_doc:
    st.info("💡 二期已支持：本地 PDF / DOCX / TXT / Markdown / PPTX，以及在线 PDF 链接、网页文章链接。扫描版 PDF 会在提取不到文本时自动尝试 OCR。")

    def save_document_result(source_key: str, result, duration: float):
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

        meta_parts = [f"文件：`{file_name}`", f"类型：`{file_type}`", f"正文：`{char_count}` 字符", f"策略：`{strategy}`", f"分块：`{chunk_count}`"]
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
            col_doc_sum, col_doc_check = st.columns([1.2, 1])
            with col_doc_sum:
                st.markdown(summary_text)
            with col_doc_check:
                st.info("🕵️ **关键声明事实核查**")
                st.markdown(fact_check_content)
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
    st.caption("系统会先自动判断文档类型。只有识别为新闻、研究、时评、政策解读、行业分析等适合核查的文档，才会自动执行关键声明事实核查。")

    doc_source_upload, doc_source_url_tab = st.tabs(["📂 本地上传", "🔗 在线链接"])

    with doc_source_upload:
        uploaded_doc = st.file_uploader(
            "上传文档",
            type=["pdf", "docx", "txt", "md", "markdown", "pptx"],
            key="doc_uploader",
            help="支持 PDF、DOCX、TXT、Markdown、PPTX，建议单文件不超过 20MB。",
        )
        doc_col1, doc_col2 = st.columns([1, 2])
        with doc_col1:
            doc_sum_btn = st.button("📄 提取并总结文档", type="primary", use_container_width=True, key="btn_doc_sum")
        with doc_col2:
            st.caption("长文档会自动分块总结；事实核查只针对关键声明进行。")

        if doc_sum_btn:
            if not uploaded_doc:
                st.warning("请先上传文档。")
            else:
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
                    else:
                        save_document_result("upload", result, doc_duration)
                        progress_bar.empty()
                        status_container.success(f"✅ 文档总结完成！耗时: {doc_duration:.1f}s")
                except Exception as e:
                    progress_bar.empty()
                    status_container.error("❌ 文档处理异常")
                    st.error(str(e))
                    st.code(traceback.format_exc())
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
            if not doc_url.strip():
                st.warning("请输入在线链接。")
            else:
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
                    else:
                        save_document_result("url", result, doc_duration)
                        progress_bar.empty()
                        status_container.success(f"✅ 在线内容总结完成！耗时: {doc_duration:.1f}s")
                except Exception as e:
                    progress_bar.empty()
                    status_container.error("❌ 在线内容处理异常")
                    st.error(str(e))
                    st.code(traceback.format_exc())
        render_document_result("url")


# ==========================
# Tab 3: 频道订阅
# ==========================
with tab_sub:
    # --- 订阅管理 (合并了添加和列表) ---
    with st.expander("📺 订阅管理 (添加 / 查看 / 删除)", expanded=False):
        # 1. 添加订阅区域
        st.markdown("##### ➕ 添加新订阅")
        new_channel_input = st.text_input("输入频道链接或关键词 (如 '李永乐')", key="sub_input")
        
        col_act_1, col_act_2 = st.columns([1, 3])
        with col_act_1:
            if st.button("🔍 搜索 / 添加", use_container_width=True):
                if not new_channel_input:
                    st.warning("请输入内容")
                else:
                    # 判断是否为 URL
                    is_url = "http" in new_channel_input or "://" in new_channel_input or new_channel_input.startswith("@") or "www." in new_channel_input or new_channel_input.startswith("BV")
                    
                    if is_url:
                        with st.spinner("正在获取频道信息..."):
                            try:
                                eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                                cid, cname, curl, cavatar, cplatform = get_channel_info(
                                    new_channel_input, 
                                    proxy_url=eff_proxy, 
                                    timeout_seconds=float(timeout)
                                )
                                exists = any(s['id'] == cid for s in st.session_state.subscriptions)
                                if exists:
                                    st.warning(f"频道 '{cname}' 已在订阅列表中")
                                else:
                                    st.session_state.subscriptions.append({
                                        "id": cid,
                                        "name": cname,
                                        "url": curl,
                                        "avatar": cavatar,
                                        "added_at": datetime.now().isoformat(),
                                        "platform": cplatform
                                    })
                                    save_subscriptions(st.session_state.subscriptions)
                                    st.success(f"已添加订阅: {cname} ({cplatform})")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"添加失败: {e}")
                    else:
                        st.session_state.search_results = None
                        with st.spinner(f"正在搜索 '{new_channel_input}' ..."):
                            eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                            results = search_channels(new_channel_input, limit=3, proxy_url=eff_proxy, timeout_seconds=float(timeout))
                            st.session_state.search_results = results
                            if not results.get("youtube") and not results.get("bilibili"):
                                st.warning("未找到相关频道")
                            else:
                                st.rerun()

        # 显示搜索结果
        if st.session_state.get("search_results"):
             st.divider()
             st.markdown("### 🔍 搜索结果")
             
             res_yt = st.session_state.search_results.get("youtube", [])
             res_b = st.session_state.search_results.get("bilibili", [])
             
             tab_res_yt, tab_res_b = st.tabs([f"YouTube ({len(res_yt)})", f"Bilibili ({len(res_b)})"])
             
             def render_search_item(item):
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
                                f'</div>',
                                unsafe_allow_html=True
                            )
                        else:
                             if item['platform'] == 'youtube':
                                 st.markdown("<div style='height: 60px; display: flex; align-items: center; justify-content: center; font-size: 30px; background-color: #f0f0f0; border-radius: 50%;'>🟥</div>", unsafe_allow_html=True)
                             else:
                                 st.markdown("<div style='height: 60px; display: flex; align-items: center; justify-content: center; font-size: 30px; background-color: #f0f0f0; border-radius: 50%;'>🟦</div>", unsafe_allow_html=True)
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
                                         item['url'], 
                                         proxy_url=eff_proxy, 
                                         timeout_seconds=float(timeout)
                                     )
                                     exists = any(s['id'] == cid for s in st.session_state.subscriptions)
                                     if exists:
                                         st.warning(f"已存在: {cname}")
                                     else:
                                         st.session_state.subscriptions.append({
                                             "id": cid,
                                             "name": cname,
                                             "url": curl,
                                             "avatar": cavatar,
                                             "added_at": datetime.now().isoformat(),
                                             "platform": cplatform
                                         })
                                         save_subscriptions(st.session_state.subscriptions)
                                         st.session_state.search_results = None
                                         st.success(f"已添加: {cname}")
                                         st.rerun()
                                 except Exception as e:
                                     st.error(f"添加失败: {e}")
             with tab_res_yt:
                 if not res_yt: st.info("无结果")
                 else:
                     for item in res_yt: render_search_item(item)
             with tab_res_b:
                 if not res_b: st.info("无结果")
                 else:
                     for item in res_b: render_search_item(item)
             if st.button("✕ 关闭搜索", key="close_search"):
                 st.session_state.search_results = None
                 st.rerun()

        st.divider()

        # 2. 订阅列表区域
        st.markdown("##### 📋 已订阅频道")
        view_mode = st.radio("视图模式", ["列表", "网格"], horizontal=True, index=0, key="sub_view_mode", label_visibility="collapsed")
        
        if not st.session_state.subscriptions:
            st.info("暂无订阅，请添加")
        else:
            yt_subs = []
            b_subs = []
            for sub in st.session_state.subscriptions:
                platform = sub.get("platform")
                if not platform:
                    u = sub.get("url", "").lower()
                    if "bilibili.com" in u: platform = "bilibili"
                    else: platform = "youtube"
                if platform == "bilibili": b_subs.append(sub)
                else: yt_subs.append(sub)
            
            def render_sub_card(sub, index_key_suffix, mode="grid"):
                real_index = st.session_state.subscriptions.index(sub)
                if mode == "grid":
                    with st.container(border=True):
                        c_mid = st.columns([1, 2, 1])
                        with c_mid[1]:
                            avatar_url = sub.get("avatar")
                            if avatar_url:
                                if avatar_url.startswith("//"): avatar_url = "https:" + avatar_url
                                st.markdown(f'<div style="display: flex; justify-content: center;"><img src="{avatar_url}" style="width: 100%; border-radius: 50%; aspect-ratio: 1/1; object-fit: cover;" referrerpolicy="no-referrer" /></div>', unsafe_allow_html=True)
                            else:
                                st.markdown("<div style='height: 80px; display: flex; align-items: center; justify-content: center; font-size: 40px;'>📺</div>", unsafe_allow_html=True)
                        name = sub['name']
                        if "马脸姐" in name: name = "马脸姐"
                        if len(name) > 8: name = name[:7] + "..."
                        st.markdown(f"<div style='text-align: center; font-weight: bold; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;' title='{sub['name']}'><a href='{sub['url']}' target='_blank' style='text-decoration: none; color: inherit;'>{name}</a></div>", unsafe_allow_html=True)
                        if st.button("🗑️", key=f"del_{real_index}_{index_key_suffix}", help=f"删除 {sub['name']}", use_container_width=True):
                            st.session_state.subscriptions.pop(real_index)
                            save_subscriptions(st.session_state.subscriptions)
                            st.rerun()
                else:
                    c_av, c_nm, c_act = st.columns([1, 4, 1])
                    with c_av:
                        avatar_url = sub.get("avatar")
                        if avatar_url:
                            if avatar_url.startswith("//"): avatar_url = "https:" + avatar_url
                            st.markdown(f'<div style="display: flex; align-items: center; height: 100%;"><img src="{avatar_url}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover;" referrerpolicy="no-referrer" /></div>', unsafe_allow_html=True)
                        else: st.markdown("📺")
                    with c_nm:
                        st.markdown(f"<div style='line-height: 32px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'><a href='{sub['url']}' target='_blank' style='text-decoration: none; color: inherit; font-weight: bold;'>{sub['name']}</a></div>", unsafe_allow_html=True)
                    with c_act:
                        if st.button("🗑️", key=f"del_list_{real_index}_{index_key_suffix}", help=f"删除 {sub['name']}"):
                            st.session_state.subscriptions.pop(real_index)
                            save_subscriptions(st.session_state.subscriptions)
                            st.rerun()
                    st.divider()

            if yt_subs:
                st.markdown("#### 🟥 YouTube")
                if view_mode == "网格":
                    cols_count = 4
                    for i in range(0, len(yt_subs), cols_count):
                        cols = st.columns(cols_count)
                        for j in range(cols_count):
                            if i + j < len(yt_subs):
                                with cols[j]:
                                    render_sub_card(yt_subs[i+j], "yt", mode="grid")
                else:
                    for sub in yt_subs: render_sub_card(sub, "yt", mode="list")
            
            if b_subs:
                if yt_subs: st.markdown("---")
                st.markdown("#### 🟦 Bilibili")
                if view_mode == "网格":
                    cols_count = 4
                    for i in range(0, len(b_subs), cols_count):
                        cols = st.columns(cols_count)
                        for j in range(cols_count):
                            if i + j < len(b_subs):
                                with cols[j]:
                                    render_sub_card(b_subs[i+j], "b", mode="grid")
                else:
                    for sub in b_subs: render_sub_card(sub, "b", mode="list")

    # --- 最新动态 (全宽) ---
    
    # 使用一个容器来包裹，确保布局正确
    with st.container():
        st.subheader("🆕 最新动态")
        
        if st.button("🔄 检查所有订阅更新", type="primary", use_container_width=True):
                # ... (原有逻辑)
                st.session_state.is_updating_all = True
                
                # 清空之前的更新内容
                st.session_state.updates = {}
                # update_container 还没定义，不需要 clear，因为代码还没跑到那里
                
                with st.status("正在检查更新...", expanded=True) as status:
                    # 添加进度条
                    progress_text = "准备开始：正在检测网络代理..."
                    progress_bar = st.progress(0, text=progress_text)
                    
                    eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                    
                    progress_bar.progress(0, text="准备开始：正在初始化检查任务...")
                    
                    # 使用线程池并发检查更新
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                # 定义单个检查任务
                def check_single_sub(sub, proxy, timeout_val):
                    try:
                        # 针对"王剑每日观察"和"大康有话说"的特殊逻辑
                        min_dur = 0
                        only_streams = False
                        
                        # 根据 ID 或名称判断
                        # 王剑: UC8UCbiPrm2zN9nZHKdTevZA
                        # 大康: (名称匹配)
                        if sub['id'] == "UC8UCbiPrm2zN9nZHKdTevZA" or "王剑" in sub['name'] or "大康" in sub['name']:
                            min_dur = 1200 # 20 分钟 (适度放宽，配合 only_streams 使用)
                            only_streams = True
                            
                        # 降低单次检查的超时时间，避免一个慢拖死全部
                        # 并且这里已经在线程池里了，可以并行等待
                        # 强制设置较短的超时时间 (20s)，因为检查 RSS/HTML 不需要太久
                        eff_timeout = min(float(timeout_val), 20.0)
                        return sub['id'], get_channel_recent_videos(
                            sub['url'], 
                            limit=5, 
                            proxy_url=proxy,
                            timeout_seconds=eff_timeout,
                            filter_longest=True,
                            min_duration_seconds=min_dur,
                            only_streams=only_streams
                        )
                    except Exception as e:
                        return sub['id'], e

                # 限制最大并发数为 20，提高并发度
                max_workers = min(len(st.session_state.subscriptions), 20)
                
                progress_bar.progress(0, text=f"正在启动 {max_workers} 个并发检查任务...")
                
                start_time = time.time()
                
                # 初始化状态显示
                status.update(label=f"正在检查更新... (已耗时 0s)", state="running")
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_sub = {
                        executor.submit(check_single_sub, sub, eff_proxy, timeout): sub 
                        for sub in st.session_state.subscriptions
                    }
                    
                    completed_count = 0
                    total_subs = len(st.session_state.subscriptions)
                    
                    # 先展示 0%
                    progress_bar.progress(0.01, text=f"(0/{total_subs}) 任务已提交，等待结果...")
                    
                    for future in as_completed(future_to_sub):
                        sub = future_to_sub[future]
                        completed_count += 1
                        pct = completed_count / total_subs
                        
                        # 计算时间
                        elapsed = time.time() - start_time
                        avg_time = elapsed / completed_count
                        remain_count = total_subs - completed_count
                        remain_time = avg_time * remain_count
                        
                        progress_bar.progress(pct, text=f"({completed_count}/{total_subs}) 正在检查: {sub['name']}... | 预计剩余: {int(remain_time)}s")
                        status.update(label=f"正在检查更新... (已耗时 {int(elapsed)}s)", state="running")
                        
                        try:
                            sid, result = future.result()
                            if isinstance(result, list):
                                if result:
                                    st.session_state.updates[sid] = result
                                    status.write(f"✅ {sub['name']}: 发现 {len(result)} 个新视频")
                                else:
                                    # status.write(f"✓ {sub['name']}: 无更新")
                                    pass
                            else:
                                # result is Exception
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

        # 显示更新内容
        update_container = st.empty()
        
        # 如果正在更新，不显示下面的内容
        if not st.session_state.get("is_updating_all", False):
            with update_container.container():
                if st.session_state.updates:
                    for sub in st.session_state.subscriptions:
                        sid = sub['id']
                        if sid in st.session_state.updates:
                            videos = st.session_state.updates[sid]
                            if not videos: continue
                            
                            # 频道标题栏
                            # 确定平台信息（用于标题栏）
                            sub_platform = sub.get('platform', '')
                            # 如果没有 platform 字段，尝试从 url 判断
                            if not sub_platform:
                                if "bilibili" in sub.get('url', '').lower():
                                    sub_platform = "bilibili"
                                else:
                                    sub_platform = "youtube"
                            
                            if sub_platform == "bilibili":
                                p_badge = "🟦 Bilibili"
                                p_color = "blue"
                            else:
                                p_badge = "🟥 YouTube"
                                p_color = "red"

                            st.markdown(f"---")
                            # 为频道名称添加链接
                            st.markdown(f"#### [{sub['name']}]({sub['url']}) :{p_color}[{p_badge}]")
                            
                            for v in videos:
                                with st.container(border=True):
                                    c1, c2 = st.columns([5, 1])

                                    with c1:
                                        # 格式化日期和时长
                                        info_parts = []
                                        # 确保每个属性只处理一次
                                        upload_date = v.get('upload_date')
                                        duration = v.get('duration')
                                        
                                        if upload_date:
                                            d = str(upload_date)
                                            if len(d) == 8:
                                                d_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                                                info_parts.append(f"{d_str}")
                                            else:
                                                info_parts.append(f"{d}")
                                        
                                        if duration:
                                            dur = duration
                                            if dur >= 3600:
                                                dur_str = f"{int(dur//3600)}小时{int((dur%3600)//60)}分"
                                            else:
                                                dur_str = f"{int(dur//60)}分{int(dur%60)}秒"
                                            info_parts.append(f"⏳ {dur_str}")
                                        
                                        # 调整标题行： 标题
                                        st.markdown(f"##### [{v['title']}]({v['url']})")
                                        st.caption(" | ".join(info_parts))
        
                                    with c2:
                                        st.write("") # Spacer
                                        # 修改：点击总结不跳转，而是在当前页面展开一个可关闭的容器
                                        summary_key = f"sub_summary_{v['id']}"
                                        
                                        # 使用 session state 来控制显示状态
                                        # 我们用一个专门的 dict 来存正在查看的总结
                                        if "viewing_summaries" not in st.session_state:
                                            st.session_state.viewing_summaries = {}
                                        
                                        if st.button("✨ 总结", key=f"btn_sum_{v['id']}", use_container_width=True):
                                            st.session_state.viewing_summaries[v['id']] = True
                                            st.rerun()
        
                                # 如果当前视频处于"查看总结"状态，在卡片下方显示 expander
                                if st.session_state.get("viewing_summaries", {}).get(v['id']):
                                    with st.container(border=True):
                                        # 优化关闭按钮布局
                                        c_head_1, c_head_2 = st.columns([15, 1])
                                        with c_head_1:
                                            st.markdown("### 📝 AI 总结")
                                        with c_head_2:
                                            # 使用更简洁的关闭图标
                                            if st.button("✕", key=f"close_{v['id']}", help="关闭总结"):
                                                st.session_state.viewing_summaries.pop(v['id'])
                                                st.rerun()
                                        
                                        # 检查是否已经有缓存的总结内容
                                        cache_key = f"cache_sum_{v['id']}"
                                        if cache_key in st.session_state:
                                            # 尝试解析缓存中的 JSON 内容
                                            summary_content = st.session_state[cache_key]
                                            is_json_summary = False
                                            summary_data = {}
                                            
                                            summary_md, fact_check_md = _parse_summary_for_ui(summary_content)
                                            if summary_md:
                                                # 使用 Tabs 替代分栏，解决拥挤问题
                                                tab_sum, tab_check = st.tabs(["📝 核心总结", "🕵️ 事实核查"])
                                                with tab_sum:
                                                    st.markdown(summary_md)
                                                with tab_check:
                                                    st.markdown(fact_check_md or "- 本次未成功拆出结构化事实核查结果。")
                                            else:
                                                st.markdown(summary_content)
                                                
                                            # 显示 Footer (如果有缓存的 metadata)
                                            meta_key = f"cache_meta_{v['id']}"
                                            if meta_key in st.session_state:
                                                st.divider()
                                                st.caption(st.session_state[meta_key])
                                        else:
                                            # 执行总结
                                            status_container = st.empty()
                                            
                                            # 进度条容器
                                            progress_container = st.empty()
                                            progress_bar = progress_container.progress(0, text="⏳ 正在初始化...")
                                            
                                            start_time = time.time()
                                            
                                            # 1. 抓取字幕
                                            progress_bar.progress(10, text="⏳ 正在准备抓取字幕/转写音频 (可能需要下载音频)...")
                                            
                                            # 使用 try-finally 确保进度条清理
                                            try:
                                                def update_progress(p, t):
                                                    progress_bar.progress(p, text=t)

                                                text, err = internal_fetch_transcript(v['url'], update_progress)
                                                
                                                if err:
                                                    progress_container.empty()
                                                    status_container.error(f"❌ 字幕获取失败: {err}")
                                                else:
                                                    progress_bar.progress(40, text="🚀 字幕获取成功，正在请求 AI 生成总结...")
                                                    status_container.info("🚀 正在请求 AI 生成总结 (流式输出)...")
                                                    
                                                    # 提取 Whisper 设备信息 (从 transcript text 中)
                                                    whisper_device_name, text = _extract_whisper_device_info(text)
                                                    whisper_device_info = f" | ⚡ Whisper引擎: {whisper_device_name}" if whisper_device_name else ""
                                                    st.session_state.whisper_device_tag = whisper_device_name
                                                    
                                                    # 2. 流式总结
                                                    if not api_key:
                                                        progress_container.empty()
                                                        status_container.error("请在侧边栏填写 API Key")
                                                    else:
                                                        try:
                                                            from core_logic import summarize_text
                                                            
                                                            progress_bar.progress(50, text="🚀 正在连接大模型 API...")
                                                            
                                                            stream = summarize_text(
                                                                text,
                                                                api_key,
                                                                base_url,
                                                                model_selected,
                                                                proxy_input,
                                                                stream=True
                                                            )
                                                            
                                                            progress_bar.progress(60, text="🚀 开始接收 AI 响应...")
                                                            time.sleep(0.2)
                                                            progress_container.empty() # 开始流式输出后隐藏进度条
                                                            
                                                            # 如果返回的是字符串（错误信息），直接显示
                                                            if isinstance(stream, str):
                                                                status_container.error(stream)
                                                            else:
                                                                # 流式显示
                                                                def stream_generator():
                                                                    full_response = ""
                                                                    # 用于缓冲，尝试检测 JSON 结构
                                                                    buffer = "" 
                                                                    is_json_mode = False
                                                                    
                                                                    for chunk in stream:
                                                                        # 处理 OpenAI 流式响应 chunk
                                                                        if chunk.choices and len(chunk.choices) > 0:
                                                                            delta = chunk.choices[0].delta
                                                                            if delta.content:
                                                                                content = delta.content
                                                                                full_response += content
                                                                                buffer += content
                                                                                
                                                                                # 简单的流式显示逻辑：
                                                                                # 如果是 JSON 模式，我们其实很难流式渲染两个 markdown 块
                                                                                # 所以流式阶段我们只显示 raw text 或者尝试提取 markdown
                                                                                # 为了体验，流式阶段我们直接输出 content，等结束后再解析 JSON
                                                                                yield content
                                                                    
                                                                    # 完成后追加 Footer (模型 + 耗时)
                                                                    end_time = time.time()
                                                                    duration = end_time - start_time
                                                                    
                                                                    # 构建 Footer 信息
                                                                    footer_str = f"本总结由 {model_selected} 模型生成{whisper_device_info} | ⏳ 总耗时: {duration:.1f}s"
                                                                    
                                                                    # 尝试提取 fetch/download 耗时
                                                                    try:
                                                                        # 检查 transcript_text 是否包含 TIMING tag
                                                                        raw_text = st.session_state.transcript_text or ""
                                                                        if "<!-- TIMING:" in raw_text:
                                                                            import re
                                                                            m_timing = re.search(r"<!-- TIMING: download=([\d\.]+), transcribe=([\d\.]+) -->", raw_text)
                                                                            if m_timing:
                                                                                dl_time = float(m_timing.group(1))
                                                                                tr_time = float(m_timing.group(2))
                                                                                footer_str += f" (📥 下载: {dl_time:.1f}s | 🎙️ 转写: {tr_time:.1f}s | 🤖 AI: {duration:.1f}s)"
                                                                    except Exception:
                                                                        pass
                                                                    
                                                                    # 缓存 Footer 信息
                                                                    st.session_state[f"cache_meta_{v['id']}"] = footer_str
                                                                    
                                                                    # 完成后存入缓存 (纯 JSON 文本，不带 footer，因为 footer 是显示层加的)
                                                                    # Wait, if we append footer to full_response, then JSON parse will fail next time.
                                                                    # So we should save pure JSON to cache if it is JSON.
                                                                    
                                                                    is_valid_json = False
                                                                    try:
                                                                        if full_response.strip().startswith("{") and full_response.strip().endswith("}"):
                                                                            json.loads(full_response)
                                                                            is_valid_json = True
                                                                    except:
                                                                        pass
                                                                        
                                                                    st.session_state[cache_key] = full_response
                                                                    
                                                                    # 只有非 JSON 才追加 Footer 到流式输出中 (JSON 模式下 Footer 会破坏结构)
                                                                    # 或者我们在显示层处理 Footer
                                                                    if not is_valid_json:
                                                                        yield f"\n\n> {footer_str}"
                                                                    
                                                                st.write_stream(stream_generator())
                                                                status_container.empty() # 清除进度提示
                                                                
                                                                # 强制刷新以触发缓存读取逻辑 (从而正确渲染分栏)
                                                                st.rerun()
                                                                
                                                        except Exception as e:
                                                            progress_container.empty()
                                                            status_container.error(f"总结过程出错: {e}")
                                            except Exception as outer_e:
                                                 progress_container.empty()
                                                 status_container.error(f"处理出错: {outer_e}")
                else:
                    if "last_update_check" in st.session_state:
                        st.info(f"检查完成 ({st.session_state.last_update_check})，暂无新内容")
                    else:
                        st.info("点击上方按钮检查更新")

# ==========================
# Tab 3: 定时任务
# ==========================
with tab_batch:
    _start_scheduler_once()
    settings, tasks, logs, runs, run_items, processed_ids = _load_scheduled_state()
    settings["timeout_seconds"] = float(settings.get("timeout_seconds") or 20.0)

    # 拆分为两个子Tab：每日简报（看结果） 和 任务管理（配任务）
    sub_tab_report, sub_tab_manage = st.tabs(["📅 每日简报", "⚙️ 任务管理"])

    # ==========================
    # Sub Tab 1: 每日简报
    # ==========================
    with sub_tab_report:
        daily_items, items_by_day = _group_items_by_day(run_items)
        if not daily_items:
            st.info("暂无更新记录，请先在“任务管理”中添加并执行任务")
        else:
            dates = [d.get("date") for d in daily_items if d.get("date")]
            today_key = _now().strftime("%Y-%m-%d")
            default_index = dates.index(today_key) if today_key in dates else 0
            
            # 顶部日期筛选区域
            filter_c1, filter_c2, filter_c3 = st.columns([2, 1, 2])
            with filter_c1:
                selected_date = st.selectbox("选择日期", dates, index=default_index, label_visibility="collapsed")
            with filter_c2:
                status_filter = st.selectbox("状态筛选", ["全部", "成功", "失败"], index=0, label_visibility="collapsed")
            with filter_c3:
                keyword = st.text_input("搜索标题", value="", placeholder="🔍 搜索更新内容...", label_visibility="collapsed")

            # 统计指标
            day_info = next((d for d in daily_items if d.get("date") == selected_date), None)
            if day_info:
                m1, m2, m3 = st.columns(3)
                m1.metric("总计更新", day_info.get("total_items"))
                m2.metric("成功", day_info.get("success_items"))
                m3.metric("失败", day_info.get("failed_items"))

            st.divider()

            items = items_by_day.get(selected_date, [])
            if not items:
                st.caption("该日期暂无更新内容")
            else:
                items_sorted = sorted(items, key=lambda i: i.get("created_at") or "", reverse=True)
                for item in items_sorted:
                    status = item.get("status") or ""
                    if status_filter == "成功" and status != "success":
                        continue
                    if status_filter == "失败" and status == "success":
                        continue
                    title = item.get("title") or "未命名内容"
                    if keyword and keyword.strip().lower() not in title.lower():
                        continue
                    
                    # 卡片式展示
                    with st.container(border=True):
                        # 头部信息：标题 + 状态
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
                        
                        # 链接与耗时
                        if item.get("url"):
                            st.caption(f"🔗 [视频链接]({item.get('url')})")
                        
                        # 内容展示
                        if status == "success":
                            with st.expander("查看 AI 总结", expanded=False):
                                # 尝试解析 JSON 总结并分栏显示
                                summary_content = item.get("summary") or ""
                                summary_md, fact_check_md = _parse_summary_for_ui(summary_content)
                                if summary_md:
                                    col_sum, col_check = st.columns([1.2, 1])
                                    with col_sum:
                                        st.markdown(summary_md)
                                    with col_check:
                                        st.info("🕵️ **新闻事实核查**")
                                        st.markdown(fact_check_md or "- 本次未成功拆出结构化事实核查结果。")
                                else:
                                    st.markdown(summary_content)
                        else:
                            err_text = item.get("error") or "未知错误"
                            st.error(f"失败原因: {err_text}")

    # ==========================
    # Sub Tab 2: 任务管理
    # ==========================
    with sub_tab_manage:
        # 1. 快捷操作
        col_quick, col_create = st.columns([1, 2])
        with col_quick:
             st.markdown("##### 🚀 快捷操作")
             if tasks:
                 if st.button("立即执行全部", type="primary", use_container_width=True):
                     with st.spinner("正在执行全部任务..."):
                         for t in tasks:
                             if not t.get("enabled"):
                                 continue
                             settings = _run_task_once(t, settings)
                         runs = settings.get("scheduled_runs") or runs
                         run_items = settings.get("scheduled_run_items") or run_items
                         processed_ids = settings.get("scheduled_processed_ids") or processed_ids
                         _save_scheduled_state(settings, tasks, settings.get("schedule_logs") or [], runs, run_items, processed_ids)
                     st.toast("已执行全部启用任务", icon="✅")
                     st.rerun()
             else:
                 st.caption("暂无可执行任务")

        with col_create:
             st.markdown("##### ➕ 新建任务")
             with st.popover("添加新任务", use_container_width=True):
                 if not st.session_state.subscriptions:
                     st.warning("请先在“频道订阅”中添加频道")
                 else:
                     # 频道选择
                    subs = st.session_state.subscriptions
                    
                    def _get_platform_icon(url):
                        if not url: return "❓"
                        if "youtube" in url or "youtu.be" in url: return "YouTube"
                        if "bilibili" in url: return "Bilibili"
                        return "❓"

                    label_map = {}
                    for s in subs:
                        plat = s.get("platform")
                        if not plat or plat == "?":
                            plat = _get_platform_icon(s.get("url"))
                        label = f"{s.get('name')} ({plat})"
                        label_map[label] = s
                    
                    # 简化搜索
                    keyword = st.text_input("搜索频道", placeholder="输入关键词...", label_visibility="collapsed")
                    filtered_labels = [l for l in label_map.keys() if keyword.lower() in l.lower()] if keyword else list(label_map.keys())
                    
                    if st.button("全选", use_container_width=True):
                         st.session_state.selected_channel_labels = filtered_labels
                         st.rerun()

                    if "selected_channel_labels" not in st.session_state:
                        st.session_state.selected_channel_labels = []
                    
                    selected_labels = st.multiselect("选择频道", filtered_labels, default=st.session_state.selected_channel_labels)
                    st.session_state.selected_channel_labels = selected_labels

                    st.divider()
                    
                    # 简化时间设置：只展示最常用的
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
                            selected_days = st.multiselect("星期", ["一","二","三","四","五","六","日"], default=["一","二","三","四","五"])
                            weekdays_value = [["一","二","三","四","五","六","日"].index(d) for d in selected_days]
                        elif schedule_type == "间隔小时":
                            interval_hours = st.number_input("每隔几小时", 1, 168, 6)
                        else:
                            cron_value = st.text_input("Cron表达式", "0 9 * * *")

                    if st.button("创建任务", type="primary", use_container_width=True):
                        if not selected_labels:
                            st.error("请选择频道")
                        else:
                            added_count = 0
                            for label in selected_labels:
                                sub = label_map[label]
                                new_task = _normalize_task({
                                    "channel_id": sub.get("id"),
                                    "channel_name": sub.get("name"),
                                    "channel_url": sub.get("url"),
                                    "platform": sub.get("platform"),
                                    "schedule_type": "daily" if schedule_type == "每天" else "weekly" if schedule_type == "每周" else "interval" if schedule_type == "间隔小时" else "cron",
                                    "time": schedule_time.strftime("%H:%M") if schedule_time else "09:00",
                                    "weekdays": weekdays_value,
                                    "interval_hours": interval_hours,
                                    "cron": cron_value,
                                    "enabled": True,
                                    "max_items": 5, # 默认值
                                    "min_duration_seconds": 0,
                                    "only_streams": False,
                                })
                                if _task_conflict(tasks, new_task): continue
                                next_run = _compute_next_run(new_task, _now())
                                new_task["next_run_at"] = _iso(next_run) if next_run else ""
                                tasks.append(new_task)
                                added_count += 1
                            _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                            if added_count > 0:
                                st.success(f"已创建 {added_count} 个任务")
                                st.rerun()
                            else:
                                st.warning("未创建任务（可能已存在）")

        st.divider()

        # 2. 任务列表
        st.markdown("##### 📝 任务列表")
        if not tasks:
            st.info("暂无任务")
        else:
            # 更新逻辑
            updated = False
            for t in tasks:
                if t.get("enabled") and not t.get("next_run_at"):
                    computed = _compute_next_run(t, _now())
                    t["next_run_at"] = _iso(computed) if computed else ""
                    updated = True
            if updated:
                _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)

            for t in tasks:
                next_run = _parse_iso(t.get("next_run_at"))
                is_enabled = t.get("enabled")
                
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 2])
                    with c1:
                        st.markdown(f"**{t.get('channel_name')}**")
                        st.caption(f"{_format_schedule_label(t)}")
                    with c2:
                        st.caption(f"下次: {next_run.strftime('%m-%d %H:%M') if next_run else '-'}")
                        if t.get("last_error"):
                            st.caption(f":red[{t.get('last_error')[:10]}...]")
                    with c3:
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                             if st.button("停用" if is_enabled else "启用", key=f"tg_{t['id']}"):
                                 t["enabled"] = not t["enabled"]
                                 _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                                 st.rerun()
                        with col_btn2:
                             if st.button("🗑️", key=f"del_{t['id']}", help="删除任务"):
                                 tasks = [x for x in tasks if x["id"] != t["id"]]
                                 _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                                 st.rerun()

# ==========================
# Tab 4: 历史记录
# ==========================
with tab_history:
    st.markdown("### 📜 全局生成记录")
    st.caption("记录所有单次和定时任务生成的总结内容")
    
    history = load_history() or []
    filter_col1, filter_col2 = st.columns([3, 1])
    with filter_col1:
        hist_kw = st.text_input("搜索历史记录 (标题/URL/内容)", key="hist_kw")
    with filter_col2:
        search_body = st.checkbox("全文搜索", value=True)
        if st.button("清空历史", use_container_width=True):
            save_history([])
            st.rerun()
    
    if not history:
        st.info("暂无历史记录")
    else:
        
        for entry in history:
            if hist_kw:
                kw = hist_kw.lower().strip()
                title_hit = kw in (entry.get("title") or "").lower()
                url_hit = kw in (entry.get("video_url") or "").lower()
                body_hit = False
                if search_body and not (title_hit or url_hit):
                    raw = entry.get("summary_text") or ""
                    summary_md_for_search, fact_md_for_search = _parse_summary_for_ui(raw)
                    body_text = (summary_md_for_search or raw) + "\n" + (fact_md_for_search or "")
                    body_hit = kw in body_text.lower()
                if not (title_hit or url_hit or body_hit):
                    continue
            
            with st.expander(f"{entry.get('timestamp')[:16].replace('T', ' ')} | {entry.get('title')}", expanded=False):
                st.caption(f"来源: {'⏰ 定时任务' if entry.get('source_type') == 'schedule' else '🎬 单次任务'} | URL: {entry.get('video_url')}")
                
                summary_content = entry.get("summary_text") or ""
                summary_md, fact_check_md = _parse_summary_for_ui(summary_content)
                if summary_md:
                    h_col1, h_col2 = st.columns([1.2, 1])
                    with h_col1:
                        st.markdown(summary_md)
                    with h_col2:
                        st.info("🕵️ **新闻事实核查**")
                        st.markdown(fact_check_md or "- 本次未成功拆出结构化事实核查结果。")
                else:
                    st.markdown(summary_content)

# ==========================
# Tab 5: 留言板
# ==========================
with tab_guestbook:
    st.markdown("### 💬 留言互动")
    st.caption("在这里记录你的想法、备忘或反馈")
    
    # 留言输入
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
                "content": message.strip()
            }
            guestbook.insert(0, new_msg)
            save_guestbook(guestbook)
            st.success("留言已发布")
            st.rerun()
            
    st.divider()
    
    # 留言列表
    guestbook = load_guestbook()
    if not guestbook:
        st.info("暂无留言，快来抢沙发吧！")
    else:
        for msg in guestbook:
            with st.chat_message("user" if msg.get("user") == "User" else "assistant", avatar="👤"):
                st.markdown(f"**{msg.get('user')}** <span style='color:gray; font-size:0.8em'> {msg.get('timestamp')[:16].replace('T', ' ')}</span>", unsafe_allow_html=True)
                st.markdown(msg.get("content"))


        # 3. 折叠的日志
        with st.expander("📜 运行日志 & 历史", expanded=False):
             tab_log, tab_hist = st.tabs(["日志", "历史"])
             with tab_log:
                 if logs:
                     st.dataframe(logs[-50:], use_container_width=True, hide_index=True)
                 else:
                     st.caption("无日志")
             with tab_hist:
                 # 简单的历史展示
                 daily_runs, _ = _group_runs_by_day(runs, run_items)
                 if not daily_runs:
                     st.caption("无历史")
                 else:
                     for day in daily_runs[:5]:
                         st.markdown(f"**{day.get('date')}**: 新增 {day.get('new_items')} | 成功 {day.get('success_items')}")
