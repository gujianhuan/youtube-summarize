
import streamlit as st
import streamlit.components.v1 as components
import threading
import time
import traceback
import json
import os
import re
import inspect
import hashlib
import html
import uuid
import calendar
import requests
from datetime import datetime, timedelta, time as dt_time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from rate_limiter import RateLimiter
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


def _resolve_default_bridge_api_url() -> str:
    configured_url = str(os.environ.get("BRIDGE_API_URL", "") or "").strip().rstrip("/")
    if configured_url:
        return configured_url
    if str(os.environ.get("RENDER", "") or "").strip():
        return "https://youtube-summarize-bridge.onrender.com"
    return "http://127.0.0.1:8765"


BRIDGE_API_URL = _resolve_default_bridge_api_url()
BRIDGE_API_TOKEN = str(os.environ.get("BRIDGE_API_TOKEN", "") or "").strip()


def _resolve_default_remote_transcribe_url() -> str:
    if not BRIDGE_API_URL:
        return ""
    return f"{BRIDGE_API_URL.rstrip('/')}/fetch-transcript"


DEFAULT_REMOTE_TRANSCRIBE_URL = _resolve_default_remote_transcribe_url()


def ensure_default_remote_transcribe_config() -> None:
    """为主站默认补齐服务端抓文本 worker 配置。"""
    current_url = str(os.environ.get("REMOTE_TRANSCRIBE_URL", "") or "").strip()
    is_render = bool(str(os.environ.get("RENDER", "") or "").strip())
    stale_ephemeral_worker = is_render and (
        "trycloudflare.com" in current_url.lower()
        or re.search(r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|$)", current_url, re.I)
    )
    if DEFAULT_REMOTE_TRANSCRIBE_URL and (not current_url or stale_ephemeral_worker):
        os.environ["REMOTE_TRANSCRIBE_URL"] = DEFAULT_REMOTE_TRANSCRIBE_URL
    if DEFAULT_REMOTE_TRANSCRIBE_URL and not str(os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "") or "").strip():
        os.environ["REMOTE_TRANSCRIBE_ENABLED"] = "1"
    if DEFAULT_REMOTE_TRANSCRIBE_URL and not str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip():
        os.environ["REMOTE_TRANSCRIBE_MODE"] = "prefer_remote"


ensure_default_remote_transcribe_config()
LEGACY_DEFAULT_SUMMARY_MODEL = "Pro/MiniMaxAI/MiniMax-M2.5"
LEGACY_DEFAULT_FACT_CHECK_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
DEFAULT_SUMMARY_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
DEFAULT_FACT_CHECK_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
UI_DEFAULT_LOCALE = "zh"
UI_TEXTS = {
    "zh": {
        "quota_remaining": "💡 您今日还可免费总结 {remaining} 个 YouTube 视频。填写您自己的 API Key 可解除限制。",
        "fact_check_label_sources": "来源出处",
        "fact_check_label_rationale": "来源线索说明",
        "fact_check_label_pending": "建议继续查看",
        "fact_check_label_conclusion": "来源定位",
        "fact_check_sources_missing": "当前未提取到可点击来源链接。",
        "fact_check_title": "🕵️ 来源导航",
        "summary_tab_label": "📝 核心总结",
        "main_title": "🎬 Video Summarizer",
        "main_caption": "轻量的视频总结工具 | 插件优先提取 | 支持 YouTube",
        "tab_home": "⚡ 立即总结",
        "tab_history": "🗂️ 历史记录",
        "tab_wishwall": "📝 留言板",
        "tab_settings": "🛠️ 设置",
        "hero_title": "快速获取视频总结",
        "hero_desc": "贴入 YouTube 链接或视频 ID，系统会优先调用浏览器插件提取 transcript 并生成总结。",
        "home_path_input_title": "输入链接调用插件",
        "home_path_input_desc": "适合直接贴视频链接。主站会请求浏览器插件在目标 YouTube 页面提取文本；如果没有安装插件或没有打开目标视频页，请先打开视频页点击插件。",
        "home_path_plugin_title": "插件一键获取总结",
        "home_path_plugin_desc": "适合在视频页直接点击插件。插件会从当前页面提取文本、上传到 bridge，然后由主站总结和核查。",
        "video_input_label": "视频链接或 ID",
        "video_input_placeholder": "粘贴 YouTube 链接或输入 11 位视频 ID",
        "video_input_meta": "支持普通视频、Shorts、直播回放和 11 位视频 ID，直接粘贴即可。",
        "video_auto_direct": "当前链接需要浏览器插件提取 transcript，请打开目标 YouTube 视频页后点击插件。",
        "video_auto_extension": "已根据当前来源自动切换为插件抓取。",
        "video_extension_fallback": "插件抓取未接管，请打开目标 YouTube 视频页后点击插件。",
        "video_extension_debug": "查看插件桥接链调试明细",
        "video_summary_title": "### 📝 AI 总结",
        "video_summary_duration": "⏱️ **总耗时: {total:.1f}s** (文本抓取: {fetch:.1f}s | AI 生成: {summary:.1f}s{fact_check_part})",
        "video_summary_pipeline": "🤖 模型流水线：{pipeline}",
        "video_fact_check_title": "🕵️ 新闻来源导航",
        "video_fact_check_running": "🕵️ 新闻来源检索正在后台补跑，完成后会自动刷新到右侧区域。",
        "video_fact_check_failed": "新闻来源检索补跑失败：{error}",
        "transcript_expander": "查看字幕原文",
        "transcript_view_label": "字幕视图",
        "view_mode_readable": "阅读版",
        "view_mode_raw": "原始版",
        "transcript_raw_caption": "原始版仅移除了内部调试标签，适合排查问题。",
        "transcript_readable_caption": "阅读版已自动清理内部标签，并按更适合阅读的形式展示。",
        "transcript_content_label": "字幕内容",
        "manual_summary_title": "### 📝 字幕总结",
        "manual_summary_duration": "⏱️ AI生成耗时: {duration:.1f}s",
        "manual_summary_source": "本次总结来源：{summary}",
        "manual_bridge_meta_expander": "查看本次总结的 bridge 元信息",
        "manual_transcript_expander": "查看粘贴的字幕原文",
        "manual_transcript_label": "字幕原文",
        "manual_info": "💡 适合浏览器扩展、第三方 transcript 或你手动复制的字幕文本。这里不负责抓取，只负责基于文本做总结。",
        "manual_source_label": "来源链接（可选）",
        "manual_source_placeholder": "https://www.youtube.com/watch?v=... 或 11位视频 ID",
        "manual_input_label": "粘贴 transcript / 字幕文本",
        "manual_input_placeholder": "把浏览器扩展提取到的字幕文本粘贴到这里...",
        "manual_summary_btn": "📝 总结字幕文本",
        "manual_fallback_caption": "适合作为 YouTube/B站抓取失败时的稳定兜底入口。",
        "manual_auto_start": "已接收到浏览器扩展传来的 transcript，正在自动开始总结...",
        "document_summary_title": "### 📄 文档总结",
        "document_strategy_chunked": "分块总结",
        "document_strategy_direct": "直接总结",
        "document_meta_file": "文件",
        "document_meta_type": "类型",
        "document_meta_body": "正文",
        "document_meta_chars": "{count} 字符",
        "document_meta_strategy": "策略",
        "document_meta_chunks": "分块",
        "document_meta_pages": "页数",
        "document_meta_duration": "耗时",
        "document_meta_ocr": "OCR：`已启用`",
        "document_meta_doc_type": "文档判定",
        "document_source_link": "来源链接：[{url}]({url})",
        "document_fact_check_status": "来源分析判定：{status}。{reason}",
        "document_fact_check_enabled": "已开启",
        "document_fact_check_skipped": "已跳过",
        "document_fact_check_title": "🕵️ 关键声明来源导航",
        "document_fact_check_tab_title": "🕵️ 关键声明来源",
        "document_fact_check_warning": "⚠️ 文档已被判定为适合做来源分析，但本次未成功生成来源结果。预期分析关键声明约 {count} 条。",
        "document_fact_check_info": "📝 当前文档功能已支持本地上传、在线链接、PPTX 和扫描 PDF OCR 回退。系统会自动判断是否需要补充关键声明的来源出处。",
        "document_expander": "查看文档原文",
        "document_view_label": "文档视图",
        "document_raw_caption": "原始版为文档提取后的原始文本，适合排查解析问题。",
        "document_readable_caption": "阅读版为清洗后的正文文本，更适合直接阅读。",
        "document_content_label": "文档内容",
        "document_info": "💡 二期已支持：本地 PDF / DOCX / TXT / Markdown / PPTX，以及在线 PDF 链接、网页文章链接。扫描版 PDF 会在提取不到文本时自动尝试 OCR。",
        "document_info_caption": "系统会先自动判断文档类型。只有识别为新闻、研究、时评、政策解读、行业分析等适合追溯出处的文档，才会自动补充关键声明来源。",
        "document_tab_upload": "📂 本地上传",
        "document_tab_url": "🔗 在线链接",
        "document_upload_caption": "支持 PDF、DOCX、TXT、Markdown、PPTX，建议单文件不超过 20MB。",
        "document_upload_label": "上传文档",
        "document_summary_btn": "📄 提取并总结文档",
        "document_upload_footer": "长文档会自动分块总结；来源分析只针对关键声明进行。",
        "document_url_label": "在线文档/文章链接",
        "document_url_placeholder": "https://example.com/report.pdf 或 https://example.com/article",
        "document_url_btn": "🌐 抓取并总结在线内容",
        "document_url_footer": "支持在线 PDF、网页文章、公开 DOCX/PPTX/TXT/Markdown 链接。",
        "document_upload_missing": "请先上传文档。",
        "copy_button_default": "复制",
        "copy_button_done": "已复制",
        "copy_button_failed": "复制失败，请手动复制下方文本",
        "issue_box_title": "诊断与问题上报",
        "issue_box_caption": "先复制诊断信息，再提交问题反馈；后续排查会更快。",
        "issue_box_copy": "复制诊断信息",
        "issue_box_preview": "诊断信息预览",
        "issue_box_reporter": "昵称",
        "issue_box_type": "问题类型",
        "issue_type_extract_failed": "提取失败",
        "issue_type_summary_failed": "总结失败",
        "issue_type_fact_check": "事实核查问题",
        "issue_type_version": "版本/部署问题",
        "issue_type_other": "其他",
        "issue_box_source_url": "来源链接（可选）",
        "issue_box_message": "问题描述",
        "issue_box_message_placeholder": "请尽量描述你做了什么、预期是什么、实际发生了什么。",
        "issue_box_submit": "提交问题",
        "issue_box_submit_success": "问题已记录，可继续把上面的诊断信息直接发给我或测试群。",
        "status_queued": "排队中",
        "status_running": "运行中",
        "status_success": "成功",
        "status_success_done": "已完成",
        "status_failed": "失败",
        "status_partial": "部分成功",
        "status_no_update": "无新增",
        "status_in_progress": "进行中",
        "status_expired": "已过期",
        "status_idle": "空闲",
        "status_unknown": "未知",
        "task_center_header": "### 📋 任务中心",
        "task_center_caption": "集中查看任务状态、失败重试、筛选搜索、批量操作和基础统计。",
        "task_metric_running": "运行中任务",
        "task_metric_failed": "失败条目",
        "task_metric_success": "成功条目",
        "task_metric_configured": "已配置自动任务",
        "task_metric_success_rate_7d": "近7天成功率",
        "task_overview": "状态概览：排队/运行 {running} | 成功 {success} | 失败 {failed} | 近7天运行批次 {runs}",
        "task_center_no_bg": "当前没有后台异步任务。你可以在“处理中心”发起视频处理，或在“订阅自动化”中创建定时任务。",
        "task_center_task_id": "任务 ID",
        "task_center_status": "状态",
        "task_center_done": "后台任务已完成。你可以清理状态后继续新任务，或在下方查看结果摘要。",
        "task_center_view_result": "查看本次结果",
        "task_center_failed": "后台任务失败：{error}",
        "task_center_retry_current": "重试当前失败任务",
        "task_center_retry_resubmitted": "已重新提交任务 {task_id}",
        "task_center_running_info": "后台任务仍在执行中，页面会自动轮询刷新。",
        "task_center_clear": "清理当前任务状态",
        "task_center_refresh": "立即刷新任务状态",
        "filter_all": "全部",
        "task_filter_status": "状态",
        "task_filter_source": "来源",
        "task_filter_search": "搜索",
        "task_filter_search_placeholder": "搜索标题 / URL / 错误信息",
        "task_filter_summary": "当前共有 {total} 条任务记录，筛选后 {filtered} 条",
        "task_batch_no_failed": "当前筛选结果中没有可批量重试的失败任务。",
        "task_batch_select": "批量选择失败任务",
        "task_unnamed": "未命名任务",
        "task_batch_select_all": "选择当前筛选中的全部失败任务",
        "task_batch_retry": "批量重试所选任务",
        "task_batch_select_warning": "请先选择要重试的失败任务。",
        "task_batch_submitted": "已批量提交 {count} 个重试任务",
        "task_meta_channel": "频道",
        "task_meta_time": "时间",
        "task_meta_link": "链接",
        "task_meta_source": "来源",
        "task_source_auto": "自动任务",
        "task_source_center": "处理中心",
        "task_source_retry": "失败重试",
        "task_source_center_retry": "处理中心失败重试",
        "task_current_title": "当前任务",
        "task_current_bg_title": "当前后台任务",
        "task_meta_task_id": "任务ID",
        "task_meta_duration": "耗时",
        "task_result_expander": "查看结果摘要",
        "task_result_empty": "本次任务未返回可展示摘要。",
        "task_failure_reason": "失败原因：{error}",
        "task_retry_single": "重试此任务",
        "task_records_empty": "暂无任务记录。",
        "task_logs_empty": "暂无运行日志。",
        "task_tab_current": "🎯 当前任务",
        "task_tab_list": "🗂️ 任务列表",
        "task_tab_logs": "🧾 运行日志",
        "history_search_label": "搜索历史记录 (标题/URL/内容)",
        "history_search_fulltext": "全文搜索",
        "history_clear": "清空历史",
        "history_source_schedule": "⏰ 定时任务",
        "history_source_single": "🎬 单次任务",
        "history_entry_caption": "来源: {source} | URL: {url}",
        "history_header": "### 🗂️ 历史记录",
        "history_caption": "查看已经生成过的总结结果，支持搜索与全文检索。",
        "history_export": "⬇️ 导出历史记录 (JSON)",
        "history_empty": "暂无历史记录，等你生成第一条总结后会自动沉淀到这里。",
        "history_count": "共 {total} 条历史记录，当前命中 {matched} 条",
        "settings_diag_header": "### 🛠️ 设置与诊断",
        "settings_diag_caption": "集中放置运行诊断和桥接状态，方便排查问题。",
        "settings_diag_pipeline": "当前双模型流水线：`{pipeline}`",
        "settings_metric_runtime": "运行版本",
        "settings_metric_bg": "后台任务",
        "settings_metric_bg_caption": "用于观察当前后台抓取与总结状态",
        "settings_metric_bridge": "Bridge 元信息",
        "settings_metric_bridge_caption": "用于判断扩展或本地工具是否已回传上下文",
        "settings_runtime_detail": "查看运行版本详情",
        "settings_runtime_detail_empty": "暂无可展示的运行版本诊断信息。",
        "settings_render_detail": "查看 Render 部署信息",
        "settings_render_deploy_hidden": "未暴露 deploy id",
        "settings_render_deploy_caption": "当前 Render 环境变量未明确暴露 deploy id；页面会优先显示 commit、branch 与 service 信息。",
        "settings_local_runtime_caption": "当前为本地运行环境，未检测到 Render 部署变量。",
        "settings_bridge_expander": "查看提取与桥接诊断",
        "settings_bridge_empty": "当前还没有可展示的 bridge 诊断数据。",
        "settings_runtime_history": "📜 运行日志 & 历史",
        "settings_runtime_log_tab": "日志",
        "settings_runtime_history_tab": "历史",
        "settings_runtime_no_log": "无日志",
        "settings_runtime_no_history": "无历史",
        "settings_runtime_day_summary": "**{date}**: 新增 {new_items} | 成功 {success_items}",
        "wish_wall_header": "### 💌 留言板",
        "wish_wall_caption": "像把便利签贴在墙上一样，任何人都可以匿名留言、查看和回复。普通用户发布后不能修改或删除。",
        "wish_wall_intro_title": "留言板",
        "wish_wall_message_label": "写下你的留言",
        "wish_wall_message_placeholder": "你可以直接写下功能建议、使用感受、Bug 反馈或想做的新能力。留言默认匿名显示，所有人都能看，也都可以继续回复。",
        "wish_wall_submit": "发布留言",
        "wish_wall_submit_success": "已贴上留言。",
        "wish_wall_empty": "现在还没有留言，来贴第一张便利签吧。",
        "wish_wall_blank_message": "（空白留言）",
        "wish_wall_note_prefix": "便利签",
        "wish_wall_reply_count": "回复 {count} 条",
        "wish_wall_view_reply": "查看与回复",
        "wish_wall_reply_label": "回复",
        "wish_wall_no_reply": "还没有回复，欢迎补充。",
        "wish_wall_reply_input": "回复内容",
        "wish_wall_reply_placeholder": "可以补充细节、回应建议，或者给这条留言点个赞。",
        "wish_wall_reply_submit": "回复",
        "wish_wall_reply_success": "回复已发布。",
        "wish_wall_admin_panel": "管理员维护",
        "wish_wall_admin_edit_label": "修改留言内容",
        "wish_wall_admin_save": "保存修改",
        "wish_wall_admin_delete": "删除留言",
        "wish_wall_admin_save_success": "留言已更新。",
        "wish_wall_admin_delete_success": "留言已删除。",
        "wish_wall_admin_delete_help": "只有管理员可删除留言及其回复。",
        "lite_settings_header": "### 🛠️ 设置",
        "lite_settings_caption": "默认无需修改。高级设置用于填写你自己的 API Key、接口地址或模型名称。",
        "lite_settings_recommend_title": "推荐用法",
        "lite_settings_recommend_body": "直接贴入视频链接即可开始使用。需要使用自己的 API Key、接口地址或模型时，再展开高级设置。",
        "lite_settings_advanced": "高级设置",
        "lite_settings_advanced_caption": "当前运行流水线：`{pipeline}`。适合需要自定义 Key、接口地址或模型的用户。",
        "lite_settings_api_key_help": "填写后将优先使用你自己的 Key，且不受每日免费次数限制。",
        "lite_settings_summary_model": "总结模型",
        "lite_settings_summary_model_help": "建议填写 deepseek-ai/DeepSeek-V4-Flash",
        "lite_settings_fact_model": "新闻核查模型",
        "lite_settings_fact_model_help": "建议填写 deepseek-ai/DeepSeek-V4-Flash",
        "lite_settings_use_defaults": "一键切到 DeepSeek-V4-Flash",
        "lite_settings_save_models": "保存模型设置",
        "lite_settings_use_defaults_success": "已切换到 DeepSeek-V4-Flash。",
        "lite_settings_save_success": "模型设置已保存。",
        "lite_settings_diag_manage": "诊断与任务管理",
        "lite_settings_diag_manage_caption": "以下内容主要用于排查问题和维护站点，普通用户一般不需要展开。",
        "lite_settings_view_task_center": "查看任务中心",
        "lite_settings_view_automation": "查看订阅自动化",
        "subscription_input_required": "请输入频道链接或关键词。",
        "subscription_fetch_channel": "正在获取频道信息...",
        "subscription_added_success": "已添加订阅: {name} ({platform})",
        "subscription_exists": "频道 '{name}' 已在订阅列表中",
        "subscription_add_failed": "添加失败: {error}",
        "subscription_searching": "正在搜索 '{keyword}' ...",
        "subscription_not_found": "未找到相关频道",
        "subscription_unknown_name": "未知频道",
        "subscription_youtube_channel": "YouTube 频道",
        "subscription_search_add": "➕ 添加",
        "subscription_added_short": "已添加: {name}",
        "subscription_exists_short": "已存在: {name}",
        "subscription_search_results": "### 🔍 搜索结果",
        "subscription_no_results": "无结果",
        "subscription_close_search": "✕ 关闭搜索",
        "subscription_delete_help": "删除 {name}",
        "subscription_list_title": "##### 📋 已订阅频道",
        "subscription_view_mode": "视图模式",
        "subscription_view_list": "列表",
        "subscription_view_grid": "网格",
        "subscription_empty": "暂无订阅，请添加",
        "subscription_channel_section": "#### 📺 已订阅频道",
        "subscription_manage_expander": "📺 订阅管理 (添加 / 查看 / 删除)",
        "subscription_add_new": "##### ➕ 添加新订阅",
        "subscription_input_label": "输入频道链接或关键词",
        "subscription_input_placeholder": "例如 李永乐 或频道链接",
        "subscription_search_button": "🔍 搜索 / 添加",
        "subscription_empty_update": "暂无订阅频道，请先添加订阅后再检查更新。",
        "subscription_checking_status": "正在检查更新...",
        "subscription_check_prepare_proxy": "准备开始：正在检测网络代理...",
        "subscription_check_prepare_tasks": "准备开始：正在初始化检查任务...",
        "subscription_check_launch": "正在启动 {count} 个并发检查任务...",
        "subscription_check_running": "正在检查更新... (已耗时 {elapsed}s)",
        "subscription_check_waiting": "({done}/{total}) 任务已提交，等待结果...",
        "subscription_check_progress": "({done}/{total}) 正在检查: {name}... | 预计剩余: {remain}s",
        "subscription_check_found": "✅ {name}: 发现 {count} 个新视频",
        "subscription_check_failed": "⚠️ {name} 检查失败: {error}",
        "subscription_check_exception": "⚠️ {name} 异常: {error}",
        "subscription_check_done_progress": "检查完成！总耗时 {elapsed}s",
        "subscription_check_done": "✅ 更新检查完成 (耗时 {elapsed}s)",
        "subscription_summary_footer": "本总结由 {pipeline} 流水线生成{device} | ⏳ 总耗时: {duration:.1f}s",
        "subscription_summary_footer_timing": " (📥 下载: {download:.1f}s | 🎙️ 转写: {transcribe:.1f}s | 🤖 AI: {duration:.1f}s)",
        "subscription_summary_close": "关闭总结",
        "subscription_summary_init": "⏳ 正在初始化...",
        "subscription_summary_prepare": "⏳ 正在准备抓取字幕/转写音频 (可能需要下载音频)...",
        "subscription_summary_transcript_failed": "❌ 字幕获取失败: {error}",
        "subscription_summary_ai_ready": "🚀 字幕获取成功，正在请求 AI 生成总结...",
        "subscription_summary_ai_dual": "🚀 正在请求 AI 生成总结（双模型流水线）...",
        "subscription_summary_ai_stream": "🚀 正在请求 AI 生成总结 (流式输出)...",
        "subscription_summary_need_api": "请在侧边栏填写 API Key",
        "subscription_summary_connect_api": "🚀 正在连接大模型 API...",
        "subscription_summary_receive": "🚀 开始接收 AI 响应...",
        "subscription_summary_error": "总结过程出错: {error}",
        "subscription_process_error": "处理出错: {error}",
        "subscription_duration_hm": "{hours}小时{minutes}分",
        "subscription_duration_ms": "{minutes}分{seconds}秒",
        "subscription_summarize_btn": "✨ 总结",
        "subscription_updates_none_after": "检查完成 ({time})，暂无新内容",
        "subscription_updates_none_before": "点击上方按钮检查更新",
        "subscription_updates_header": "🆕 最新动态",
        "subscription_updates_check_all": "🔄 检查所有订阅更新",
        "daily_report_select_date": "选择日期",
        "daily_report_filter_status": "状态筛选",
        "daily_report_filter_success": "成功",
        "daily_report_filter_failed": "失败",
        "daily_report_search_title": "搜索标题",
        "daily_report_search_placeholder": "🔍 搜索更新内容...",
        "daily_report_metric_total": "总计更新",
        "daily_report_item_untitled": "未命名内容",
        "daily_report_video_link": "视频链接",
        "daily_report_view_summary": "查看 AI 总结",
        "daily_report_empty": "暂无更新记录，请先在“任务管理”中添加并执行任务",
        "daily_report_empty_date": "该日期暂无更新内容",
        "daily_report_empty_filter": "没有符合当前筛选条件的更新内容",
        "automation_quick_actions": "##### 🚀 快捷操作",
        "automation_no_tasks": "暂无可执行任务",
        "automation_run_all": "立即执行全部",
        "automation_running_all": "正在执行全部任务...",
        "automation_run_all_done": "已执行全部启用任务",
        "automation_create_task_title": "##### ➕ 新建任务",
        "automation_create_task_btn": "添加新任务",
        "automation_create_task_need_sub": "请先在“频道订阅”中添加频道",
        "automation_search_channel": "搜索频道",
        "automation_search_channel_placeholder": "输入关键词...",
        "automation_select_all": "全选",
        "automation_select_channels": "选择频道",
        "automation_schedule_title": "⏰ 时间设置",
        "automation_simple_mode": "简单模式",
        "automation_schedule_type": "周期类型",
        "automation_schedule_daily": "每天",
        "automation_schedule_weekly": "每周",
        "automation_schedule_interval": "间隔小时",
        "automation_schedule_cron": "Cron",
        "automation_schedule_daily_time": "每天几点运行",
        "automation_schedule_time_point": "时间点",
        "automation_schedule_weekdays": "星期",
        "automation_schedule_interval_hours": "每隔几小时",
        "automation_schedule_cron_expr": "Cron表达式",
        "automation_weekday_mon": "周一",
        "automation_weekday_tue": "周二",
        "automation_weekday_wed": "周三",
        "automation_weekday_thu": "周四",
        "automation_weekday_fri": "周五",
        "automation_weekday_sat": "周六",
        "automation_weekday_sun": "周日",
        "automation_create_task_submit": "创建任务",
        "automation_create_task_pick_channel": "请选择频道",
        "automation_create_task_success": "已创建 {count} 个任务",
        "automation_create_task_skip_exists": "未创建任务（可能已存在）",
        "automation_task_next_run": "下次: {time}",
        "automation_task_toggle_disable": "停用",
        "automation_task_toggle_enable": "启用",
        "automation_task_delete_help": "删除任务",
        "automation_task_list_title": "##### 📝 任务列表",
        "automation_task_list_empty": "暂无任务",
        "automation_daily_tab": "📅 每日简报",
        "automation_manage_tab": "⚙️ 任务管理",
        "automation_header": "### 📡 订阅自动化",
        "automation_caption": "把频道订阅、更新检查和定时执行放到同一个页面中，统一管理自动化能力。",
        "automation_tab_subs": "📺 订阅与动态",
        "automation_tab_rules": "⏰ 规则与日报",
        "automation_countdown_soon": "即将执行",
        "automation_countdown_day": "{count}天",
        "automation_countdown_hour": "{count}小时",
        "automation_countdown_minute": "{count}分",
        "automation_task_missing_channel": "任务缺少频道链接，已跳过",
        "automation_task_missing_api": "缺少 API Key，无法生成总结",
        "automation_task_run_done": "任务执行完成，新增 {count} 个视频",
        "automation_task_retry_scheduled": "任务失败，将在 5 分钟后重试({retry}/3)：{error}",
        "automation_task_retry_exhausted": "任务失败并超过最大重试次数：{error}",
        "schedule_label_daily": "每天 {time}",
        "schedule_label_weekly": "{days} {time}",
        "schedule_label_interval": "每 {hours} 小时",
        "schedule_label_unset": "未设置",
    },
    "en": {
        "quota_remaining": "💡 You can still summarize {remaining} YouTube videos for free today. Add your own API key to remove the limit.",
        "fact_check_label_sources": "Source Links",
        "fact_check_label_rationale": "Source Notes",
        "fact_check_label_pending": "Suggested Follow-ups",
        "fact_check_label_conclusion": "Source Status",
        "fact_check_sources_missing": "No clickable source links were extracted.",
        "fact_check_title": "🕵️ Source Guide",
        "summary_tab_label": "📝 Summary",
        "main_title": "🎬 Video Summarizer",
        "main_caption": "Lightweight video summarizer | Extension-first extraction | YouTube supported",
        "tab_home": "⚡ Summarize",
        "tab_history": "🗂️ History",
        "tab_wishwall": "📝 Board",
        "tab_settings": "🛠️ Settings",
        "hero_title": "Get a Video Summary Fast",
        "hero_desc": "Paste a YouTube URL or video ID. The app asks the browser extension to extract the transcript first.",
        "home_path_input_title": "Paste Link, Use Extension",
        "home_path_input_desc": "Best when you already have the video URL. The site asks the browser extension to extract text on the target YouTube page. If the extension is missing or the target page is not open, open the video page and click the extension.",
        "home_path_plugin_title": "One-Click From Extension",
        "home_path_plugin_desc": "Best on the video page itself. The extension extracts text from the current page, uploads it to the bridge, then the main site summarizes and checks sources.",
        "video_input_label": "Video URL or ID",
        "video_input_placeholder": "Paste a YouTube URL or enter an 11-character video ID",
        "video_input_meta": "Supports regular videos, Shorts, archived livestreams, and 11-character video IDs.",
        "video_auto_direct": "This link needs browser-extension transcript extraction. Open the target YouTube page and click the extension.",
        "video_auto_extension": "Automatically switched to extension-based extraction for this source.",
        "video_extension_fallback": "The extension did not take over. Open the target YouTube page and click the extension.",
        "video_extension_debug": "View extension bridge debug details",
        "video_summary_title": "### 📝 AI Summary",
        "video_summary_duration": "⏱️ **Total: {total:.1f}s** (Fetch: {fetch:.1f}s | AI: {summary:.1f}s{fact_check_part})",
        "video_summary_pipeline": "🤖 Model pipeline: {pipeline}",
        "video_fact_check_title": "🕵️ News Source Guide",
        "video_fact_check_running": "🕵️ Source discovery is still running in the background and will refresh automatically when ready.",
        "video_fact_check_failed": "Background source discovery failed: {error}",
        "transcript_expander": "View Transcript",
        "transcript_view_label": "Transcript View",
        "view_mode_readable": "Readable",
        "view_mode_raw": "Raw",
        "transcript_raw_caption": "Raw view only removes internal debug tags and is useful for troubleshooting.",
        "transcript_readable_caption": "Readable view cleans internal tags and formats the transcript for easier reading.",
        "transcript_content_label": "Transcript",
        "manual_summary_title": "### 📝 Transcript Summary",
        "manual_summary_duration": "⏱️ AI time: {duration:.1f}s",
        "manual_summary_source": "Summary source: {summary}",
        "manual_bridge_meta_expander": "View bridge metadata for this summary",
        "manual_transcript_expander": "View Pasted Transcript",
        "manual_transcript_label": "Transcript",
        "manual_info": "💡 Best for browser extensions, third-party transcripts, or text you pasted manually. This entry only summarizes text and does not fetch it.",
        "manual_source_label": "Source URL (optional)",
        "manual_source_placeholder": "https://www.youtube.com/watch?v=... or an 11-character video ID",
        "manual_input_label": "Paste transcript text",
        "manual_input_placeholder": "Paste the transcript extracted by the browser extension here...",
        "manual_summary_btn": "📝 Summarize Transcript",
        "manual_fallback_caption": "Useful as a stable fallback when YouTube or Bilibili extraction fails.",
        "manual_auto_start": "Transcript received from the browser extension. Starting summarization automatically...",
        "document_summary_title": "### 📄 Document Summary",
        "document_strategy_chunked": "Chunked summary",
        "document_strategy_direct": "Direct summary",
        "document_meta_file": "File",
        "document_meta_type": "Type",
        "document_meta_body": "Body",
        "document_meta_chars": "{count} chars",
        "document_meta_strategy": "Strategy",
        "document_meta_chunks": "Chunks",
        "document_meta_pages": "Pages",
        "document_meta_duration": "Time",
        "document_meta_ocr": "OCR: `enabled`",
        "document_meta_doc_type": "Document type",
        "document_source_link": "Source: [{url}]({url})",
        "document_fact_check_status": "Fact-check status: {status}. {reason}",
        "document_fact_check_enabled": "enabled",
        "document_fact_check_skipped": "skipped",
        "document_fact_check_title": "🕵️ Key Claim Source Guide",
        "document_fact_check_tab_title": "🕵️ Key Claim Sources",
        "document_fact_check_warning": "⚠️ This document was marked as suitable for source analysis, but no source output was produced this time. Estimated key claims: {count}.",
        "document_fact_check_info": "📝 Document mode supports local uploads, online links, PPTX, and OCR fallback for scanned PDFs. The app decides automatically whether key-claim source discovery is needed.",
        "document_expander": "View Source Document",
        "document_view_label": "Document View",
        "document_raw_caption": "Raw view shows the extracted source text and is useful for debugging parsing issues.",
        "document_readable_caption": "Readable view shows cleaned body text for easier reading.",
        "document_content_label": "Document Content",
        "document_info": "💡 Document mode supports local PDF / DOCX / TXT / Markdown / PPTX files and online PDF or article links. Scanned PDFs automatically fall back to OCR when needed.",
        "document_info_caption": "The app first classifies the document type. Only content such as news, research, commentary, policy analysis, or industry reports will trigger key-claim fact checking automatically.",
        "document_tab_upload": "📂 Upload",
        "document_tab_url": "🔗 Online Link",
        "document_upload_caption": "Supports PDF, DOCX, TXT, Markdown, and PPTX. Recommended size: under 20MB.",
        "document_upload_label": "Upload document",
        "document_summary_btn": "📄 Extract and Summarize",
        "document_upload_footer": "Long documents are summarized in chunks; fact checking only targets key claims.",
        "document_url_label": "Online document/article URL",
        "document_url_placeholder": "https://example.com/report.pdf or https://example.com/article",
        "document_url_btn": "🌐 Fetch and Summarize",
        "document_url_footer": "Supports online PDF, article pages, and public DOCX / PPTX / TXT / Markdown links.",
        "document_upload_missing": "Please upload a document first.",
        "copy_button_default": "Copy",
        "copy_button_done": "Copied",
        "copy_button_failed": "Copy failed. Please copy the text below manually.",
        "issue_box_title": "Diagnostics and Feedback",
        "issue_box_caption": "Copy the diagnostics first, then submit feedback to speed up troubleshooting.",
        "issue_box_copy": "Copy Diagnostics",
        "issue_box_preview": "Diagnostics Preview",
        "issue_box_reporter": "Name",
        "issue_box_type": "Issue Type",
        "issue_type_extract_failed": "Extraction failed",
        "issue_type_summary_failed": "Summary failed",
        "issue_type_fact_check": "Fact check issue",
        "issue_type_version": "Version/deployment issue",
        "issue_type_other": "Other",
        "issue_box_source_url": "Source URL (optional)",
        "issue_box_message": "Description",
        "issue_box_message_placeholder": "Describe what you did, what you expected, and what actually happened.",
        "issue_box_submit": "Submit Feedback",
        "issue_box_submit_success": "The issue has been recorded. You can continue sharing the diagnostics above with me or the test group.",
        "status_queued": "Queued",
        "status_running": "Running",
        "status_success": "Success",
        "status_success_done": "Completed",
        "status_failed": "Failed",
        "status_partial": "Partially succeeded",
        "status_no_update": "No update",
        "status_in_progress": "In progress",
        "status_expired": "Expired",
        "status_idle": "Idle",
        "status_unknown": "Unknown",
        "task_center_header": "### 📋 Task Center",
        "task_center_caption": "View task states, retries, filters, batch actions, and basic metrics in one place.",
        "task_metric_running": "Running tasks",
        "task_metric_failed": "Failed items",
        "task_metric_success": "Successful items",
        "task_metric_configured": "Configured automations",
        "task_metric_success_rate_7d": "7-day success rate",
        "task_overview": "Overview: queued/running {running} | success {success} | failed {failed} | runs in last 7 days {runs}",
        "task_center_no_bg": "There is no background async task right now. Start a video task from the processing center or create a scheduled task from automation.",
        "task_center_task_id": "Task ID",
        "task_center_status": "Status",
        "task_center_done": "The background task has finished. Clear the state to continue, or review the result below.",
        "task_center_view_result": "View Result",
        "task_center_failed": "Background task failed: {error}",
        "task_center_retry_current": "Retry Current Failed Task",
        "task_center_retry_resubmitted": "Resubmitted task {task_id}",
        "task_center_running_info": "The background task is still running. This page will refresh automatically.",
        "task_center_clear": "Clear Current Task State",
        "task_center_refresh": "Refresh Now",
        "filter_all": "All",
        "task_filter_status": "Status",
        "task_filter_source": "Source",
        "task_filter_search": "Search",
        "task_filter_search_placeholder": "Search title / URL / error",
        "task_filter_summary": "{total} task records in total, {filtered} after filtering",
        "task_batch_no_failed": "No failed tasks are available for batch retry under the current filter.",
        "task_batch_select": "Select failed tasks in batch",
        "task_unnamed": "Untitled task",
        "task_batch_select_all": "Select all failed tasks in the current filter",
        "task_batch_retry": "Retry Selected Tasks",
        "task_batch_select_warning": "Select at least one failed task to retry.",
        "task_batch_submitted": "Submitted {count} retry tasks in batch",
        "task_meta_channel": "Channel",
        "task_meta_time": "Time",
        "task_meta_link": "Link",
        "task_meta_source": "Source",
        "task_source_auto": "Automation",
        "task_source_center": "Processing Center",
        "task_source_retry": "Retry",
        "task_source_center_retry": "Processing Center Retry",
        "task_current_title": "Current Task",
        "task_current_bg_title": "Current Background Task",
        "task_meta_task_id": "Task ID",
        "task_meta_duration": "Duration",
        "task_result_expander": "View Summary",
        "task_result_empty": "This task did not return any displayable summary.",
        "task_failure_reason": "Failure reason: {error}",
        "task_retry_single": "Retry This Task",
        "task_records_empty": "No task records yet.",
        "task_logs_empty": "No task logs yet.",
        "task_tab_current": "🎯 Current Task",
        "task_tab_list": "🗂️ Task List",
        "task_tab_logs": "🧾 Logs",
        "history_search_label": "Search history (title/URL/content)",
        "history_search_fulltext": "Full-text search",
        "history_clear": "Clear History",
        "history_source_schedule": "⏰ Scheduled task",
        "history_source_single": "🎬 One-off task",
        "history_entry_caption": "Source: {source} | URL: {url}",
        "history_header": "### 🗂️ History",
        "history_caption": "Browse generated summaries with search and full-text lookup.",
        "history_export": "⬇️ Export History (JSON)",
        "history_empty": "No history yet. Your first generated summary will appear here automatically.",
        "history_count": "{total} history items in total, {matched} matched now",
        "settings_diag_header": "### 🛠️ Settings and Diagnostics",
        "settings_diag_caption": "Shows runtime diagnostics and bridge state in one place for troubleshooting.",
        "settings_diag_pipeline": "Current dual-model pipeline: `{pipeline}`",
        "settings_metric_runtime": "Runtime",
        "settings_metric_bg": "Background Tasks",
        "settings_metric_bg_caption": "Used to observe current background fetching and summarization state",
        "settings_metric_bridge": "Bridge Metadata",
        "settings_metric_bridge_caption": "Used to confirm whether extension or local-tool context has been returned",
        "settings_runtime_detail": "View Runtime Details",
        "settings_runtime_detail_empty": "No runtime diagnostics are available right now.",
        "settings_render_detail": "View Render Deployment Info",
        "settings_render_deploy_hidden": "deploy id not exposed",
        "settings_render_deploy_caption": "Render did not explicitly expose the deploy id, so the page prioritizes commit, branch, and service info.",
        "settings_local_runtime_caption": "Running locally. No Render deployment variables were detected.",
        "settings_bridge_expander": "View Extraction and Bridge Diagnostics",
        "settings_bridge_empty": "No bridge diagnostics are available yet.",
        "settings_runtime_history": "📜 Runtime Logs and History",
        "settings_runtime_log_tab": "Logs",
        "settings_runtime_history_tab": "History",
        "settings_runtime_no_log": "No logs",
        "settings_runtime_no_history": "No history",
        "settings_runtime_day_summary": "**{date}**: new {new_items} | success {success_items}",
        "wish_wall_header": "### 💌 Message Board",
        "wish_wall_caption": "Like sticky notes on a wall: anyone can post anonymously, view, and reply. Regular users cannot edit or delete posts after publishing.",
        "wish_wall_intro_title": "Message Board",
        "wish_wall_message_label": "Write your message",
        "wish_wall_message_placeholder": "Share feature ideas, usage feedback, bug reports, or new capabilities you want. Messages are anonymous by default and everyone can view and reply.",
        "wish_wall_submit": "Post Message",
        "wish_wall_submit_success": "Your message has been posted.",
        "wish_wall_empty": "No messages yet. Add the first sticky note.",
        "wish_wall_blank_message": "(blank message)",
        "wish_wall_note_prefix": "Note",
        "wish_wall_reply_count": "{count} replies",
        "wish_wall_view_reply": "View and Reply",
        "wish_wall_reply_label": "Reply",
        "wish_wall_no_reply": "No replies yet. Feel free to add one.",
        "wish_wall_reply_input": "Reply",
        "wish_wall_reply_placeholder": "Add details, respond to the suggestion, or simply show support.",
        "wish_wall_reply_submit": "Reply",
        "wish_wall_reply_success": "Reply posted.",
        "wish_wall_admin_panel": "Admin maintenance",
        "wish_wall_admin_edit_label": "Edit message content",
        "wish_wall_admin_save": "Save changes",
        "wish_wall_admin_delete": "Delete message",
        "wish_wall_admin_save_success": "Message updated.",
        "wish_wall_admin_delete_success": "Message deleted.",
        "wish_wall_admin_delete_help": "Only admins can delete a message and its replies.",
        "lite_settings_header": "### 🛠️ Settings",
        "lite_settings_caption": "You usually do not need to change anything here. Advanced settings are for your own API key, endpoint, or model names.",
        "lite_settings_recommend_title": "Recommended Usage",
        "lite_settings_recommend_body": "Paste a video URL and start right away. Expand advanced settings only when you need your own API key, endpoint, or model names.",
        "lite_settings_advanced": "Advanced Settings",
        "lite_settings_advanced_caption": "Current pipeline: `{pipeline}`. Best for users who need custom keys, endpoints, or models.",
        "lite_settings_api_key_help": "If provided, your own API key is used first and daily free limits no longer apply.",
        "lite_settings_summary_model": "Summary Model",
        "lite_settings_summary_model_help": "Recommended: deepseek-ai/DeepSeek-V4-Flash",
        "lite_settings_fact_model": "Fact Check Model",
        "lite_settings_fact_model_help": "Recommended: deepseek-ai/DeepSeek-V4-Flash",
        "lite_settings_use_defaults": "Switch to DeepSeek-V4-Flash",
        "lite_settings_save_models": "Save Model Settings",
        "lite_settings_use_defaults_success": "Switched to DeepSeek-V4-Flash.",
        "lite_settings_save_success": "Model settings saved.",
        "lite_settings_diag_manage": "Diagnostics and Task Management",
        "lite_settings_diag_manage_caption": "The content below is mainly for troubleshooting and site maintenance. Most users do not need to expand it.",
        "lite_settings_view_task_center": "View Task Center",
        "lite_settings_view_automation": "View Automation",
        "subscription_input_required": "Please enter a channel link or keyword.",
        "subscription_fetch_channel": "Fetching channel information...",
        "subscription_added_success": "Subscription added: {name} ({platform})",
        "subscription_exists": "Channel '{name}' is already in subscriptions",
        "subscription_add_failed": "Add failed: {error}",
        "subscription_searching": "Searching '{keyword}' ...",
        "subscription_not_found": "No related channels found",
        "subscription_unknown_name": "Unknown channel",
        "subscription_youtube_channel": "YouTube channel",
        "subscription_search_add": "➕ Add",
        "subscription_added_short": "Added: {name}",
        "subscription_exists_short": "Already exists: {name}",
        "subscription_search_results": "### 🔍 Search Results",
        "subscription_no_results": "No results",
        "subscription_close_search": "✕ Close Search",
        "subscription_delete_help": "Remove {name}",
        "subscription_list_title": "##### 📋 Subscriptions",
        "subscription_view_mode": "View mode",
        "subscription_view_list": "List",
        "subscription_view_grid": "Grid",
        "subscription_empty": "No subscriptions yet. Add one first.",
        "subscription_channel_section": "#### 📺 Subscribed Channels",
        "subscription_manage_expander": "📺 Subscription Management (Add / View / Remove)",
        "subscription_add_new": "##### ➕ Add Subscription",
        "subscription_input_label": "Enter a channel link or keyword",
        "subscription_input_placeholder": "For example, a channel name or URL",
        "subscription_search_button": "🔍 Search / Add",
        "subscription_empty_update": "No subscribed channels yet. Add subscriptions before checking updates.",
        "subscription_checking_status": "Checking updates...",
        "subscription_check_prepare_proxy": "Getting ready: checking proxy settings...",
        "subscription_check_prepare_tasks": "Getting ready: initializing update tasks...",
        "subscription_check_launch": "Starting {count} concurrent update tasks...",
        "subscription_check_running": "Checking updates... ({elapsed}s elapsed)",
        "subscription_check_waiting": "({done}/{total}) Tasks submitted. Waiting for results...",
        "subscription_check_progress": "({done}/{total}) Checking {name}... | ETA: {remain}s",
        "subscription_check_found": "✅ {name}: found {count} new videos",
        "subscription_check_failed": "⚠️ {name} check failed: {error}",
        "subscription_check_exception": "⚠️ {name} exception: {error}",
        "subscription_check_done_progress": "Update check finished. Total time: {elapsed}s",
        "subscription_check_done": "✅ Update check finished ({elapsed}s)",
        "subscription_summary_footer": "Generated by the {pipeline} pipeline{device} | ⏳ Total: {duration:.1f}s",
        "subscription_summary_footer_timing": " (📥 Download: {download:.1f}s | 🎙️ Transcribe: {transcribe:.1f}s | 🤖 AI: {duration:.1f}s)",
        "subscription_summary_close": "Close summary",
        "subscription_summary_init": "⏳ Initializing...",
        "subscription_summary_prepare": "⏳ Preparing transcript fetch/audio transcription (audio download may be required)...",
        "subscription_summary_transcript_failed": "❌ Transcript fetch failed: {error}",
        "subscription_summary_ai_ready": "🚀 Transcript ready. Requesting AI summary...",
        "subscription_summary_ai_dual": "🚀 Requesting AI summary (dual-model pipeline)...",
        "subscription_summary_ai_stream": "🚀 Requesting AI summary (streaming output)...",
        "subscription_summary_need_api": "Please enter an API key in the sidebar",
        "subscription_summary_connect_api": "🚀 Connecting to the model API...",
        "subscription_summary_receive": "🚀 Receiving AI response...",
        "subscription_summary_error": "Summary generation error: {error}",
        "subscription_process_error": "Processing error: {error}",
        "subscription_duration_hm": "{hours}h {minutes}m",
        "subscription_duration_ms": "{minutes}m {seconds}s",
        "subscription_summarize_btn": "✨ Summarize",
        "subscription_updates_none_after": "Check completed ({time}). No new content found.",
        "subscription_updates_none_before": "Click the button above to check for updates",
        "subscription_updates_header": "🆕 Latest Updates",
        "subscription_updates_check_all": "🔄 Check All Subscription Updates",
        "daily_report_select_date": "Date",
        "daily_report_filter_status": "Status",
        "daily_report_filter_success": "Success",
        "daily_report_filter_failed": "Failed",
        "daily_report_search_title": "Search title",
        "daily_report_search_placeholder": "🔍 Search updates...",
        "daily_report_metric_total": "Total updates",
        "daily_report_item_untitled": "Untitled content",
        "daily_report_video_link": "Video link",
        "daily_report_view_summary": "View AI Summary",
        "daily_report_empty": "No update records yet. Add and run tasks from Task Management first.",
        "daily_report_empty_date": "No updates for this date",
        "daily_report_empty_filter": "No updates match the current filters",
        "automation_quick_actions": "##### 🚀 Quick Actions",
        "automation_no_tasks": "No runnable tasks",
        "automation_run_all": "Run All Now",
        "automation_running_all": "Running all tasks...",
        "automation_run_all_done": "All enabled tasks have been executed",
        "automation_create_task_title": "##### ➕ Create Task",
        "automation_create_task_btn": "Add New Task",
        "automation_create_task_need_sub": "Add a channel in Subscriptions first",
        "automation_search_channel": "Search channels",
        "automation_search_channel_placeholder": "Enter keywords...",
        "automation_select_all": "Select All",
        "automation_select_channels": "Select channels",
        "automation_schedule_title": "⏰ Schedule Settings",
        "automation_simple_mode": "Simple mode",
        "automation_schedule_type": "Schedule type",
        "automation_schedule_daily": "Daily",
        "automation_schedule_weekly": "Weekly",
        "automation_schedule_interval": "Interval hours",
        "automation_schedule_cron": "Cron",
        "automation_schedule_daily_time": "Run time each day",
        "automation_schedule_time_point": "Time",
        "automation_schedule_weekdays": "Weekdays",
        "automation_schedule_interval_hours": "Run every N hours",
        "automation_schedule_cron_expr": "Cron expression",
        "automation_weekday_mon": "Mon",
        "automation_weekday_tue": "Tue",
        "automation_weekday_wed": "Wed",
        "automation_weekday_thu": "Thu",
        "automation_weekday_fri": "Fri",
        "automation_weekday_sat": "Sat",
        "automation_weekday_sun": "Sun",
        "automation_create_task_submit": "Create Task",
        "automation_create_task_pick_channel": "Please select at least one channel",
        "automation_create_task_success": "Created {count} tasks",
        "automation_create_task_skip_exists": "No tasks were created (they may already exist)",
        "automation_task_next_run": "Next: {time}",
        "automation_task_toggle_disable": "Disable",
        "automation_task_toggle_enable": "Enable",
        "automation_task_delete_help": "Delete task",
        "automation_task_list_title": "##### 📝 Task List",
        "automation_task_list_empty": "No tasks yet",
        "automation_daily_tab": "📅 Daily Report",
        "automation_manage_tab": "⚙️ Task Management",
        "automation_header": "### 📡 Subscription Automation",
        "automation_caption": "Manage subscriptions, update checks, and scheduled runs in one place.",
        "automation_tab_subs": "📺 Subscriptions & Updates",
        "automation_tab_rules": "⏰ Rules & Reports",
        "automation_countdown_soon": "Starting soon",
        "automation_countdown_day": "{count}d",
        "automation_countdown_hour": "{count}h",
        "automation_countdown_minute": "{count}m",
        "automation_task_missing_channel": "Task skipped because the channel URL is missing",
        "automation_task_missing_api": "API key is missing, so the summary cannot be generated",
        "automation_task_run_done": "Task finished with {count} new videos",
        "automation_task_retry_scheduled": "Task failed and will retry in 5 minutes ({retry}/3): {error}",
        "automation_task_retry_exhausted": "Task failed and exceeded the maximum retry count: {error}",
        "schedule_label_daily": "Daily {time}",
        "schedule_label_weekly": "{days} {time}",
        "schedule_label_interval": "Every {hours} hours",
        "schedule_label_unset": "Not set",
    },
}


def _get_request_headers() -> dict:
    try:
        return dict(st.context.headers or {})
    except Exception:
        return {}


def _normalize_ui_locale(raw_locale: str) -> str:
    normalized = str(raw_locale or "").strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return ""


def detect_browser_ui_locale() -> str:
    headers = _get_request_headers()
    accept_language = str(
        headers.get("accept-language")
        or headers.get("Accept-Language")
        or ""
    ).strip()
    for token in accept_language.split(","):
        locale = _normalize_ui_locale(token.split(";")[0])
        if locale:
            return locale
    return UI_DEFAULT_LOCALE


def get_ui_locale() -> str:
    current = _normalize_ui_locale(st.session_state.get("ui_locale"))
    if current:
        return current
    detected = detect_browser_ui_locale()
    st.session_state.ui_locale = detected
    return detected


def t(key: str, **kwargs) -> str:
    locale = get_ui_locale()
    template = (
        UI_TEXTS.get(locale, {}).get(key)
        or UI_TEXTS[UI_DEFAULT_LOCALE].get(key)
        or key
    )
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _automation_weekday_labels() -> list[str]:
    return [
        t("automation_weekday_mon"),
        t("automation_weekday_tue"),
        t("automation_weekday_wed"),
        t("automation_weekday_thu"),
        t("automation_weekday_fri"),
        t("automation_weekday_sat"),
        t("automation_weekday_sun"),
    ]

# --- 限流器初始化 ---
rate_limiter = RateLimiter(max_daily=3)


def get_client_ip() -> str:
    """获取客户端 IP 地址，兼容 Render/Cloudflare/Nginx 代理。"""
    try:
        # Streamlit 1.35+ 推荐使用 st.context.headers
        headers = _get_request_headers()
        # 常见代理头
        x_forwarded_for = headers.get("x-forwarded-for")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        
        # 针对部分特定环境的备选头
        remote_addr = headers.get("remote-addr")
        if remote_addr:
            return remote_addr
            
        return "127.0.0.1"
    except Exception:
        return "unknown"


def render_quota_status():
    """渲染当前用户的配额状态。"""
    if rate_limiter.is_owner(st.session_state.settings):
        return
        
    client_ip = get_client_ip()
    allowed, msg = rate_limiter.check_limit(client_ip)
    
    user_data = rate_limiter.limits.get(client_ip, {"count": 0})
    count = user_data.get("count", 0)
    remaining = max(0, rate_limiter.max_daily - count)
    
    if remaining > 0:
        st.info(t("quota_remaining", remaining=remaining))
    else:
        st.warning(msg)


def is_admin_user() -> bool:
    """Return true only for site maintenance users, not regular users with their own API key."""
    configured_token = str(
        os.environ.get("ADMIN_TOKEN")
        or st.session_state.get("settings", {}).get("admin_token")
        or ""
    ).strip()
    if not configured_token:
        return False
    try:
        supplied_token = str(st.query_params.get("admin_token", "") or "").strip()
    except Exception:
        supplied_token = ""
    return bool(supplied_token and supplied_token == configured_token)


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


def _remap_siliconflow_legacy_model(model_value: str, fallback_value: str) -> str:
    model_text = str(model_value or "").strip()
    if not model_text:
        return str(fallback_value or "").strip()
    legacy_map = {
        LEGACY_DEFAULT_SUMMARY_MODEL: DEFAULT_SUMMARY_MODEL,
        LEGACY_DEFAULT_FACT_CHECK_MODEL: DEFAULT_FACT_CHECK_MODEL,
    }
    return legacy_map.get(model_text, model_text)


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
    if _looks_like_siliconflow_base_url(base_url_value):
        summary_model = _remap_siliconflow_legacy_model(summary_model, DEFAULT_SUMMARY_MODEL)
        fact_check_model = _remap_siliconflow_legacy_model(fact_check_model, DEFAULT_FACT_CHECK_MODEL)
    return summary_model, fact_check_model


def normalize_persisted_pipeline_settings(settings_dict: dict | None = None) -> dict:
    """把 SiliconFlow 下的历史默认模型名归一为当前默认值，避免显示与实际运行不一致。"""
    settings_dict = dict(settings_dict or {})
    base_url_value = str(settings_dict.get("base_url") or "").strip()
    if not _looks_like_siliconflow_base_url(base_url_value):
        return settings_dict

    normalized_summary, normalized_fact_check = resolve_pipeline_models(
        settings_dict,
        env={},
        base_url_value=base_url_value,
    )
    changed = False
    if str(settings_dict.get("summary_model") or "").strip() != normalized_summary:
        settings_dict["summary_model"] = normalized_summary
        changed = True
    if str(settings_dict.get("fact_check_model") or "").strip() != normalized_fact_check:
        settings_dict["fact_check_model"] = normalized_fact_check
        changed = True
    if not str(settings_dict.get("model") or "").strip():
        settings_dict["model"] = normalized_summary
        changed = True
    settings_dict["_normalized_pipeline_models"] = changed
    return settings_dict


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


def get_session_history() -> list[dict]:
    history = st.session_state.get("session_history")
    if isinstance(history, list):
        return history
    st.session_state.session_history = []
    return st.session_state.session_history


def save_session_history(history: list[dict]) -> None:
    st.session_state.session_history = list(history or [])


def add_session_history_entry(source_type, video_url, summary_text, transcript_text=""):
    history = get_session_history()
    title = "未命名视频"
    try:
        if str(summary_text or "").strip().startswith("{"):
            data = json.loads(summary_text)
            md = data.get("summary_markdown", "")
            for line in str(md or "").split("\n"):
                if "核心主题" in line or "核心一句话" in line:
                    continue
                if line.strip() and not line.startswith("#"):
                    title = line.strip()
                    break
    except Exception:
        pass

    entry_id = str(uuid.uuid4())
    entry = {
        "id": entry_id,
        "timestamp": _iso(_now()),
        "source_type": source_type,
        "video_url": video_url,
        "title": title,
        "summary_text": summary_text,
    }
    history.insert(0, entry)
    if len(history) > 50:
        history = history[:50]
    save_session_history(history)
    return entry_id

def load_guestbook():
    return load_json_file(GUESTBOOK_FILE, [])

def save_guestbook(guestbook):
    save_json_file(GUESTBOOK_FILE, guestbook)


def append_guestbook_message(content: str):
    guestbook = load_guestbook()
    guestbook.insert(
        0,
        {
            "id": str(uuid.uuid4()),
            "timestamp": _iso(_now()),
            "content": str(content or "").strip(),
            "replies": [],
        },
    )
    save_guestbook(guestbook)


def append_guestbook_reply(message_id: str, reply_text: str) -> bool:
    guestbook = load_guestbook()
    updated = False
    for item in guestbook:
        if str(item.get("id") or "") != str(message_id or ""):
            continue
        replies = item.get("replies")
        if not isinstance(replies, list):
            replies = []
            item["replies"] = replies
        replies.append(
            {
                "id": str(uuid.uuid4()),
                "timestamp": _iso(_now()),
                "content": str(reply_text or "").strip(),
            }
        )
        updated = True
        break
    if updated:
        save_guestbook(guestbook)
    return updated


def update_guestbook_message(message_id: str, content: str) -> bool:
    guestbook = load_guestbook()
    updated = False
    for item in guestbook:
        if str(item.get("id") or "") != str(message_id or ""):
            continue
        item["content"] = str(content or "").strip()
        item["updated_at"] = _iso(_now())
        updated = True
        break
    if updated:
        save_guestbook(guestbook)
    return updated


def delete_guestbook_message(message_id: str) -> bool:
    guestbook = load_guestbook()
    next_guestbook = [
        item for item in guestbook
        if str(item.get("id") or "") != str(message_id or "")
    ]
    if len(next_guestbook) == len(guestbook):
        return False
    save_guestbook(next_guestbook)
    return True

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
    button_label = html.escape(str(label or t("copy_button_default")))
    text_payload = json.dumps(str(text or ""), ensure_ascii=False)
    copied_text = json.dumps(t("copy_button_done"), ensure_ascii=False)
    failed_text = json.dumps(t("copy_button_failed"), ensure_ascii=False)
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
          status.textContent = {copied_text};
            setTimeout(() => status.textContent = "", 1500);
          }} catch (err) {{
          status.textContent = {failed_text};
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
    box_title: str | None = None,
) -> None:
    snapshot = build_issue_diagnostics_snapshot(
        context_label,
        source_url=source_url,
        error_text=error_text,
        extra=extra,
    )
    diag_text = format_issue_diagnostics_text(snapshot)
    with st.expander(box_title or t("issue_box_title"), expanded=expanded):
        st.caption(t("issue_box_caption"))
        render_copy_to_clipboard_button(t("issue_box_copy"), diag_text, f"{key_prefix}_copy")
        st.text_area(
            t("issue_box_preview"),
            diag_text,
            height=180,
            key=f"{key_prefix}_diag_preview",
        )
        with st.form(f"{key_prefix}_feedback_form", clear_on_submit=True):
            reporter = st.text_input(t("issue_box_reporter"), value="User", max_chars=20)
            issue_type = st.selectbox(
                t("issue_box_type"),
                [
                    t("issue_type_extract_failed"),
                    t("issue_type_summary_failed"),
                    t("issue_type_fact_check"),
                    t("issue_type_version"),
                    t("issue_type_other"),
                ],
                key=f"{key_prefix}_issue_type",
            )
            report_source_url = st.text_input(
                t("issue_box_source_url"),
                value=str(source_url or ""),
                key=f"{key_prefix}_source_url",
            )
            report_message = st.text_area(
                t("issue_box_message"),
                value=str(error_text or ""),
                height=120,
                placeholder=t("issue_box_message_placeholder"),
                key=f"{key_prefix}_message",
            )
            submitted = st.form_submit_button(t("issue_box_submit"))
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
                st.success(t("issue_box_submit_success"))

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


def _looks_like_youtube_comments_panel_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    head = "\n".join(value.splitlines()[:12])
    return (
        bool(re.search(r"(^|\n)\s*评论\s*(\n|$)", head))
        and bool(re.search(r"(^|\n)\s*(最热门|最新|显示精选评论|显示近期评论)", head))
        and not bool(re.search(r"\b\d{1,2}:\d{2}\b", head))
    )


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
    if _looks_like_youtube_comments_panel_text(transcript_text):
        transcript_text = ""
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
    if not (is_admin_user() or str(source_type or "").strip() == "schedule"):
        return add_session_history_entry(source_type, video_url, summary_text, transcript_text)
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
    
    entry_id = str(uuid.uuid4())
    entry = {
        "id": entry_id,
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
    return entry_id


def update_history_entry_summary(entry_id: str, summary_text: str) -> bool:
    """按历史记录 ID 回写最新总结内容，用于补充异步完成的新闻核查结果。"""
    normalized_entry_id = str(entry_id or "").strip()
    if not normalized_entry_id:
        return False

    history = load_history()
    updated = False
    for entry in history:
        if str(entry.get("id") or "").strip() != normalized_entry_id:
            continue
        entry["summary_text"] = str(summary_text or "")
        updated = True
        break

    if updated:
        save_history(history)
    return updated


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


def _repair_mojibake_text(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""

    def _score(candidate: str) -> tuple[int, int]:
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", candidate))
        mojibake_count = sum(candidate.count(marker) for marker in ("Ã", "Â", "â", "æ", "å", "ç", "ï", "ð", "�"))
        return cjk_count, -mojibake_count

    original_score = _score(value)
    suspicious = "�" in value or original_score[1] < -1
    if not suspicious:
        return value

    best = value
    best_score = original_score
    for source_encoding in ("latin-1", "cp1252"):
        try:
            repaired = value.encode(source_encoding, errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            continue
        if not repaired.strip():
            continue
        repaired_score = _score(repaired)
        if repaired_score > best_score:
            best = repaired
            best_score = repaired_score
    return best


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
                summary_md = _repair_mojibake_text(str(data.get("summary_markdown") or data.get("summary") or "").strip())
                fact_md = str(
                    data.get("fact_check_markdown")
                    or data.get("fact_check")
                    or data.get("factcheck_markdown")
                    or ""
                ).strip()
                fact_md = _repair_mojibake_text(fact_md)
                if summary_md:
                    return summary_md, fact_md
        except Exception:
            continue

    summary_md = _repair_mojibake_text(_extract_field(text, ["summary_markdown", "summary", "summary_md"]))
    fact_md = _repair_mojibake_text(_extract_field(text, ["fact_check_markdown", "fact_check", "factcheck_markdown", "fact_check_md"]))
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
        r"(?=^(?:###\s*(?:条目|Item)\s*\d+|\d+\.\s*(?:新闻/声明|关键声明|声明|新闻|Claim|Statement|News Claim|News)[:：]))",
        text,
        flags=re.M,
    )
    return [part.strip() for part in parts if part and part.strip()]


def _parse_fact_check_section(section_text: str) -> dict[str, object]:
    """解析单条来源分析结果，拆出标题、来源状态、说明、后续建议和来源链接。"""
    section = str(section_text or "").strip()
    lines = [line.rstrip() for line in section.splitlines()]
    title = ""
    conclusion = ""
    rationale_lines: list[str] = []
    pending_lines: list[str] = []
    body_lines: list[str] = []
    source_lines: list[str] = []
    active_field = ""
    generic_title_pattern = re.compile(r"^(?:条目|Item)\s*\d+$", re.I)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if active_field in {"rationale", "pending", "source"}:
                target = (
                    rationale_lines
                    if active_field == "rationale"
                    else pending_lines
                    if active_field == "pending"
                    else source_lines
                )
                if target and target[-1] != "":
                    target.append("")
            continue
        claim_match = re.search(r"(?:新闻/声明|关键声明|声明|新闻|Claim|Statement|News Claim|News)[:：]\s*(.+)", stripped, re.I)
        if claim_match and (not title or generic_title_pattern.match(title)):
            title = claim_match.group(1).strip()
            active_field = ""
            continue
        if not title and stripped.startswith("###"):
            title = stripped.lstrip("#").strip()
            active_field = ""
            continue
        conclusion_match = re.search(r"(?:核查结论|来源定位|检索状态|Conclusion|Source Status)[:：]\s*(.+)", stripped, re.I)
        if conclusion_match and not conclusion:
            conclusion = conclusion_match.group(1).strip()
            active_field = ""
            continue
        rationale_match = re.search(r"(?:判断依据|依据|来源线索说明|线索说明|Rationale|Source Notes)[:：]\s*(.*)", stripped, re.I)
        if rationale_match:
            rationale_text = rationale_match.group(1).strip()
            if rationale_text:
                rationale_lines.append(rationale_text)
            active_field = "rationale"
            continue
        pending_match = re.search(r"(?:待补充核查点|建议继续查看|后续建议|Follow-up Checks|Suggested Follow-ups)[:：]\s*(.*)", stripped, re.I)
        if pending_match:
            pending_text = pending_match.group(1).strip()
            if pending_text:
                pending_lines.append(pending_text)
            active_field = "pending"
            continue
        if re.search(r"(?:来源(?:链接|/出处|出处)?|Sources?|Source Links?)[:：]", stripped, re.I):
            source_lines.append(stripped)
            active_field = "source"
            continue
        if active_field == "rationale":
            rationale_lines.append(stripped)
            continue
        if active_field == "pending":
            pending_lines.append(stripped)
            continue
        if active_field == "source":
            if re.match(r"^(?:[-*]\s+|\d+\.\s+|\[[^\]]+\]\(https?://)", stripped):
                source_lines.append(stripped)
                continue
            active_field = ""
        body_lines.append(line)

    if not title:
        title = "来源分析"

    source_block = "\n".join(_dedupe_text_lines(source_lines)).strip()
    source_links = _extract_markdown_links(source_block) if source_block else []
    if not source_links:
        source_links = _extract_markdown_links(section)
    body_markdown = "\n".join(body_lines).strip()
    rationale_markdown = "\n".join(line for line in rationale_lines).strip()
    pending_markdown = "\n".join(line for line in pending_lines).strip()
    source_summary = source_block
    return {
        "title": title,
        "conclusion": conclusion,
        "rationale_markdown": rationale_markdown,
        "pending_markdown": pending_markdown,
        "body_markdown": body_markdown,
        "source_links": source_links,
        "source_summary": source_summary,
    }


def _call_with_optional_kwargs(func, /, *args, **kwargs):
    """兼容热重载时旧函数对象暂未携带新增参数的情况。"""
    try:
        supported = set(inspect.signature(func).parameters.keys())
    except Exception:
        supported = set()
    filtered_kwargs = {key: value for key, value in kwargs.items() if key in supported}
    return func(*args, **filtered_kwargs)


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


def _normalize_fact_check_source_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        filtered_query_pairs = []
        for key, value in parse_qsl(parsed.query or "", keep_blank_values=True):
            lowered_key = str(key or "").strip().lower()
            if not lowered_key:
                continue
            if (
                lowered_key.startswith("utm_")
                or lowered_key in {
                    "ved", "ei", "usg", "at", "ref", "ref_src", "feature", "fbclid", "gclid",
                    "igshid", "mc_cid", "mc_eid", "src", "source", "spm", "from", "mkt_tok",
                }
            ):
                continue
            filtered_query_pairs.append((key, value))
        normalized_path = re.sub(r"/+$", "", parsed.path or "")
        normalized_query = urlencode(filtered_query_pairs, doseq=True)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, normalized_query, ""))
    except Exception:
        return raw


def _dedupe_text_lines(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = str(line or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _render_source_links(source_links: list[tuple[str, str]]) -> None:
    """将来源列表渲染为简洁链接列表。"""
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in source_links:
        raw_url = str(url or "").strip()
        normalized = _normalize_fact_check_source_url(raw_url)
        if not raw_url or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append((str(label or "").strip() or raw_url, raw_url))
    if not deduped:
        st.caption(t("fact_check_sources_missing"))
        return
    _render_fact_check_label(t("fact_check_label_sources"))
    source_lines = [f"- [{label}]({url})" for label, url in deduped[:12]]
    st.markdown("\n".join(source_lines))


def _build_fact_check_search_entry_links(title: str, rationale_markdown: str = "") -> list[tuple[str, str]]:
    query_candidates: list[str] = []
    title_value = re.sub(r"\s+", " ", str(title or "")).strip()
    if title_value and title_value != "来源分析":
        query_candidates.append(title_value)

    rationale_text = str(rationale_markdown or "")
    inline_terms = re.findall(r"`([^`]{6,160})`", rationale_text)
    for term in inline_terms:
        cleaned = re.sub(r"\s+", " ", str(term or "")).strip()
        if cleaned:
            query_candidates.append(cleaned)

    query = ""
    seen: set[str] = set()
    merged_terms: list[str] = []
    for candidate in query_candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        merged_terms.append(normalized)
        if len(merged_terms) >= 2:
            break
    if merged_terms:
        query = " ".join(merged_terms)
    if not query:
        return []

    encoded = quote(query[:240])
    return [
        ("Google 新闻搜索", f"https://www.google.com/search?tbm=nws&q={encoded}"),
        ("Google 网页搜索", f"https://www.google.com/search?q={encoded}"),
        ("Bing 新闻搜索", f"https://www.bing.com/news/search?q={encoded}"),
        ("Bing 网页搜索", f"https://www.bing.com/search?q={encoded}"),
        ("AnySearch", f"https://anysearch.com/search?q={encoded}"),
    ]


def _is_fact_check_search_entry_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
        host = str(parsed.netloc or "").lower()
        return (
            "google." in host
            or host in {"bing.com", "www.bing.com", "anysearch.com", "www.anysearch.com"}
            or raw.startswith("https://anysearch.com/search")
        )
    except Exception:
        return bool(re.search(r"https?://(?:www\.)?(?:google|bing|anysearch)\.", raw, re.I))


def render_fact_check_content(fact_check_md: str, *, fact_title: str | None = None) -> None:
    """渲染以来源链接为中心的来源分析结果。"""
    text = str(fact_check_md or "").strip()
    if not text:
        return
    st.markdown(
        (
            "<div class='summary-workspace-title'>"
            "<span class='summary-workspace-kicker'>核</span>"
            f"<span>{html.escape(fact_title or t('fact_check_title'))}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    sections = _split_fact_check_sections(text)
    if not sections:
        st.markdown(text)
        return

    for idx, section in enumerate(sections, start=1):
        parsed = _parse_fact_check_section(section)
        title = str(parsed.get("title") or f"条目 {idx}")
        conclusion = str(parsed.get("conclusion") or "").strip()
        st.markdown("<div class='fact-check-item'>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='fact-check-item-title'>{idx}. {html.escape(title)}</div>",
            unsafe_allow_html=True,
        )
        if conclusion:
            st.markdown(
                f"<div class='fact-check-status-chip'>{html.escape(conclusion)}</div>",
                unsafe_allow_html=True,
            )
        source_links = list(parsed.get("source_links") or [])
        rationale_markdown = str(parsed.get("rationale_markdown") or "").strip()
        has_only_search_entries = bool(source_links) and all(
            _is_fact_check_search_entry_url(url) for _label, url in source_links
        )
        if not source_links or has_only_search_entries:
            fallback_links = _build_fact_check_search_entry_links(title, rationale_markdown)
            existing_urls = {_normalize_fact_check_source_url(url) for _label, url in source_links}
            source_links = [
                *source_links,
                *[
                    (label, url)
                    for label, url in fallback_links
                    if _normalize_fact_check_source_url(url) not in existing_urls
                ],
            ]
        _render_source_links(source_links)
        source_summary = str(parsed.get("source_summary") or "").strip()
        if source_summary and not parsed.get("source_links"):
            st.caption(source_summary)
        if rationale_markdown:
            _render_fact_check_label(t("fact_check_label_rationale"))
            st.markdown(rationale_markdown)
        pending_markdown = str(parsed.get("pending_markdown") or "").strip()
        if pending_markdown:
            _render_fact_check_label(t("fact_check_label_pending"))
            st.markdown(pending_markdown)
        body_markdown = str(parsed.get("body_markdown") or "").strip()
        if body_markdown:
            st.markdown(body_markdown)
        st.markdown("</div>", unsafe_allow_html=True)


def render_summary_fact_check(
    summary_md: str,
    fact_check_md: str,
    *,
    fact_title: str | None = None,
    summary_tab_label: str | None = None,
    fact_tab_label: str | None = None,
) -> None:
    """统一渲染总结与事实核查，优先使用同页左右布局。"""
    has_fact_check = bool(str(fact_check_md or "").strip())
    resolved_summary_tab_label = summary_tab_label or t("summary_tab_label")
    resolved_fact_title = fact_title or t("fact_check_title")
    if not has_fact_check:
        with st.container(border=True):
            st.markdown(
                (
                    "<div class='summary-workspace-title'>"
                    "<span class='summary-workspace-kicker'>摘</span>"
                    f"<span>{html.escape(resolved_summary_tab_label)}</span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            st.markdown(summary_md)
        return

    st.markdown("<div class='summary-fact-workspace'>", unsafe_allow_html=True)
    col_sum, col_check = st.columns([1.15, 0.95], gap="large")
    with col_sum:
        with st.container(border=True):
            st.markdown("<div class='summary-workspace-panel'>", unsafe_allow_html=True)
            st.markdown(
                (
                    "<div class='summary-workspace-title'>"
                    "<span class='summary-workspace-kicker'>摘</span>"
                    f"<span>{html.escape(resolved_summary_tab_label)}</span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            st.markdown(summary_md)
            st.markdown("</div>", unsafe_allow_html=True)
    with col_check:
        with st.container(border=True):
            st.markdown("<div class='summary-workspace-panel fact-workspace-panel'>", unsafe_allow_html=True)
            render_fact_check_content(fact_check_md, fact_title=resolved_fact_title)
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_summary_content(
    summary_content: str,
    *,
    fact_title: str = "🕵️ 来源导航",
    fact_tab_label: str = "🕵️ 来源导航",
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


def render_browser_title_status(status: str, *, running_title: str, done_title: str) -> None:
    """更新浏览器标签页标题，方便用户离开页面后看到后台任务状态。"""
    status_value = str(status or "").strip().lower()
    if status_value in {"queued", "running"}:
        title = running_title
    elif status_value == "success":
        title = done_title
    else:
        title = "YouTube Summarizer"
    components.html(
        f"""
        <script>
        try {{
          window.parent.document.title = {json.dumps(title, ensure_ascii=False)};
        }} catch (error) {{}}
        </script>
        """,
        height=0,
    )


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
        "success": t("status_success"),
        "partial": t("status_partial"),
        "failed": t("status_failed"),
        "no_update": t("status_no_update"),
        "running": t("status_in_progress"),
    }
    return status_map.get(status or "", t("status_unknown"))

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
        _append_log(logs, "error", t("automation_task_missing_channel"), task.get("id"))
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
                item_record["error"] = t("automation_task_missing_api")
                item_record["duration_seconds"] = int((_now() - item_start).total_seconds())
                run_entry["failed_items"] += 1
                run_items.append(item_record)
                continue
            try:
                summary = _call_with_optional_kwargs(
                    summarize_text,
                    text,
                    api_key,
                    base_url,
                    summary_model_name,
                    eff_proxy,
                    fact_check_model=fact_check_model_name,
                    ui_locale=get_ui_locale(),
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
        _append_log(
            logs,
            "info",
            t("automation_task_run_done", count=run_entry.get("new_items") or 0),
            task.get("id"),
        )
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
            _append_log(
                logs,
                "warning",
                t("automation_task_retry_scheduled", retry=retry_count, error=e),
                task.get("id"),
            )
        else:
            task["next_retry_at"] = ""
            _append_log(
                logs,
                "error",
                t("automation_task_retry_exhausted", error=e),
                task.get("id"),
            )
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
        return t("automation_countdown_soon")
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    parts = []
    if days > 0:
        parts.append(t("automation_countdown_day", count=days))
    if hours > 0:
        parts.append(t("automation_countdown_hour", count=hours))
    parts.append(t("automation_countdown_minute", count=minutes))
    return "".join(parts)

def _format_schedule_label(task):
    schedule_type = (task.get("schedule_type") or "").lower()
    if schedule_type == "daily":
        return t("schedule_label_daily", time=task.get("time"))
    if schedule_type == "weekly":
        weekdays = task.get("weekdays") or []
        labels = _automation_weekday_labels()
        day_text = "、".join([labels[i] for i in weekdays if isinstance(i, int) and 0 <= i <= 6])
        return t("schedule_label_weekly", days=day_text, time=task.get("time"))
    if schedule_type == "interval":
        return t("schedule_label_interval", hours=task.get("interval_hours"))
    if schedule_type == "cron":
        return f"Cron: {task.get('cron')}"
    return t("schedule_label_unset")

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
    page_icon="📺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 界面美化 CSS ---
st.markdown(
    """
    <style>
    /* 全局容器优化 */
    .block-container {
        padding-top: 0.75rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 1400px;
    }

    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    .stDeployButton {
        display: none !important;
    }
    
    /* 标题样式 */
    h1, h2, h3 {
        font-family: 'Inter', sans-serif;
        font-weight: 700 !important;
        color: #1E1E1E;
    }
    
    /* 顶部 Hero 区域 */
    .lite-home-hero {
        text-align: center;
        margin: 4.5rem auto 1.2rem auto;
        max-width: 800px;
        padding: 2.5rem;
        background: linear-gradient(135deg, #fdfbfb 0%, #ebedee 100%);
        border-radius: 32px;
        box-shadow: 0 20px 40px rgba(0,0,0,0.05);
    }
    
    .lite-home-hero h1 {
        font-size: 3rem !important;
        background: linear-gradient(45deg, #FF0000, #CC0000);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
        font-weight: 800 !important;
    }
    
    .lite-home-hero p {
        color: #666;
        font-size: 1.2rem;
        margin-top: 1rem;
    }

    .lite-search-meta {
        max-width: 1040px;
        margin: 0.45rem auto 0.7rem auto;
        text-align: center;
        color: #7a7a7a;
        font-size: 0.93rem;
    }

    .lite-entry-card {
        padding: 0.15rem 0.1rem;
    }

    .lite-entry-card-title {
        font-size: 1rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 0.35rem;
    }

    .lite-entry-card-desc {
        color: #667085;
        font-size: 0.93rem;
        line-height: 1.65;
        margin: 0;
    }

    .summary-section-title {
        margin-bottom: 0.3rem;
    }

    .summary-section-meta {
        color: #6b7280;
        font-size: 0.92rem;
        margin: -0.15rem 0 0.35rem 0;
    }

    .summary-fact-workspace {
        margin-top: 0.25rem;
    }

    .summary-workspace-panel {
        min-height: 0;
        padding: 0.15rem 0.05rem;
    }

    .summary-workspace-title {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        margin-bottom: 0.65rem;
        font-size: 1.05rem;
        font-weight: 750;
        color: #111827;
    }

    .summary-workspace-kicker {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.7rem;
        height: 1.7rem;
        border-radius: 8px;
        background: #fff1f2;
        color: #be123c;
        font-size: 0.92rem;
        font-weight: 800;
    }

    .fact-workspace-panel {
        position: static;
    }

    .fact-check-item {
        padding: 0.85rem 0;
        border-top: 1px solid #edf0f3;
    }

    .fact-check-item:first-of-type {
        border-top: 0;
        padding-top: 0.2rem;
    }

    .fact-check-item-title {
        margin: 0 0 0.45rem 0;
        font-size: 0.98rem;
        line-height: 1.45;
        font-weight: 720;
        color: #111827;
    }

    .fact-check-status-chip {
        display: inline-flex;
        margin: 0.15rem 0 0.45rem 0;
        padding: 0.2rem 0.5rem;
        border-radius: 999px;
        background: #eef6ff;
        color: #155e75;
        font-size: 0.78rem;
        font-weight: 700;
        border: 1px solid #d8ecff;
    }

    .st-key-input_url {
        max-width: 1040px;
        margin: 0.2rem auto 0.1rem auto;
    }

    .st-key-input_url input {
        min-height: 4rem !important;
        font-size: 1.02rem !important;
        font-weight: 500 !important;
        padding-left: 1.35rem !important;
        padding-right: 1.35rem !important;
        border-radius: 999px !important;
        border: 1px solid #e8e8e8 !important;
        background: #ffffff !important;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06) !important;
    }

    .st-key-input_url input:focus {
        border-color: #ff7d7f !important;
        background: #ffffff !important;
        box-shadow: 0 0 0 4px rgba(255, 125, 127, 0.1), 0 12px 28px rgba(255, 125, 127, 0.08) !important;
    }

    .wish-wall-shell {
        margin-top: 0.8rem;
    }

    .wish-wall-intro {
        padding: 1rem 1.1rem;
        border-radius: 18px;
        background: linear-gradient(180deg, #fffef7 0%, #fff9eb 100%);
        border: 1px solid #f3e8c8;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        margin-bottom: 1rem;
    }

    .wish-note {
        min-height: 220px;
        padding: 1rem 1rem 0.85rem 1rem;
        border-radius: 18px;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
        margin-bottom: 1rem;
        border: 1px solid rgba(0, 0, 0, 0.05);
    }

    .wish-note-yellow {
        background: linear-gradient(180deg, #fff8b8 0%, #fff29b 100%);
    }

    .wish-note-pink {
        background: linear-gradient(180deg, #ffe1ea 0%, #ffd2df 100%);
    }

    .wish-note-blue {
        background: linear-gradient(180deg, #ddefff 0%, #cfe7ff 100%);
    }

    .wish-note-green {
        background: linear-gradient(180deg, #e2f7d9 0%, #d6f0ca 100%);
    }

    .wish-note-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #6b5b2a;
        font-size: 0.85rem;
        margin-bottom: 0.55rem;
    }

    .wish-note-body {
        color: #2f2f2f;
        font-size: 1rem;
        line-height: 1.65;
        white-space: pre-wrap;
        word-break: break-word;
        margin-bottom: 0.8rem;
    }

    .wish-note-reply-count {
        color: #666;
        font-size: 0.83rem;
    }

    .lite-settings-card {
        padding: 1.1rem 1.15rem;
        border-radius: 18px;
        background: linear-gradient(180deg, #ffffff 0%, #fafafa 100%);
        border: 1px solid #f0f0f0;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        margin-bottom: 1rem;
    }
    
    /* 任务提示框 */
    .lite-home-task-tip {
        background-color: #f0f7ff;
        border-left: 4px solid #FF0000;
        padding: 1rem;
        border-radius: 12px;
        margin: 1.5rem 0;
        font-size: 0.95rem;
        color: #333;
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
    }
    
    /* 按钮美化 */
    .stButton > button {
        border-radius: 16px !important;
        padding: 0.6rem 2.5rem !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        font-weight: 600 !important;
        border: none !important;
        background: #FF0000 !important;
        color: white !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(255, 0, 0, 0.3);
        background: #CC0000 !important;
    }
    
    /* 输入框美化 */
    .stTextInput > div > div > input {
        border-radius: 16px !important;
        padding: 1rem 1.5rem !important;
        border: 2px solid #EEE !important;
        transition: all 0.3s ease !important;
        font-size: 1.1rem !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #FF0000 !important;
        box-shadow: 0 0 0 4px rgba(255, 0, 0, 0.1) !important;
    }
    
    /* 选项卡样式 */
    div[data-testid="stTabs"] button[role="tab"] {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        padding: 0.8rem 2rem !important;
        border-radius: 12px 12px 0 0 !important;
    }
    
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: #FF0000 !important;
        border-bottom-color: #FF0000 !important;
    }
    
    /* 侧边栏美化 */
    section[data-testid="stSidebar"] {
        background-color: #F8F9FA;
        border-right: 1px solid #EEE;
    }
    
    /* 文件上传区域 */
    div[data-testid="stFileUploaderDropzone"] {
        border-radius: 20px !important;
        border: 2px dashed #DDD !important;
        padding: 2rem !important;
    }
    
    /* 文本溢出处理 */
    div[data-testid="stMarkdownContainer"] {
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    
    .st-key-btn_single_sum,
    .st-key-btn_single_check {
        max-width: 200px;
        margin: 0 auto;
    }
    
    .lite-home-helper {
        text-align: center;
        margin: 0.85rem auto 0 auto;
        max-width: 720px;
        font-size: 0.92rem;
        color: #5f6368;
    }
    
    @media (max-width: 900px) {
        .block-container {
            padding-left: 0.85rem;
            padding-right: 0.85rem;
        }
        .lite-home-hero {
            margin-top: 2.2rem;
            margin-bottom: 1rem;
        }
        .lite-home-hero h1 {
            font-size: 1.85rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Session State 初始化 ---
if "settings" not in st.session_state:
    st.session_state.settings = load_settings()
normalized_settings = normalize_persisted_pipeline_settings(st.session_state.settings)
if normalized_settings.pop("_normalized_pipeline_models", False):
    st.session_state.settings = normalized_settings
    save_settings(normalized_settings)
else:
    st.session_state.settings = normalized_settings

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
if "video_extension_allow_local_fallback" not in st.session_state:
    st.session_state.video_extension_allow_local_fallback = False
if "video_extension_local_fallback_attempted" not in st.session_state:
    st.session_state.video_extension_local_fallback_attempted = False
if "current_video_url" not in st.session_state:
    st.session_state.current_video_url = ""
if "video_extension_auto_summary_pending" not in st.session_state:
    st.session_state.video_extension_auto_summary_pending = False
if "video_extension_auto_summary_url" not in st.session_state:
    st.session_state.video_extension_auto_summary_url = ""
if "video_extension_auto_summary_fetch_duration" not in st.session_state:
    st.session_state.video_extension_auto_summary_fetch_duration = 0.0
if "video_auto_fetch_pending" not in st.session_state:
    st.session_state.video_auto_fetch_pending = False
if "video_auto_fetch_url" not in st.session_state:
    st.session_state.video_auto_fetch_url = ""
if "video_auto_fetch_route" not in st.session_state:
    st.session_state.video_auto_fetch_route = ""
if "video_auto_fetch_last_signature" not in st.session_state:
    st.session_state.video_auto_fetch_last_signature = ""
if "current_processing_task" not in st.session_state:
    st.session_state.current_processing_task = {}
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
if "manual_video_fact_check_task_id" not in st.session_state:
    st.session_state.manual_video_fact_check_task_id = ""
if "manual_video_fact_check_status" not in st.session_state:
    st.session_state.manual_video_fact_check_status = "idle"
if "manual_video_fact_check_error" not in st.session_state:
    st.session_state.manual_video_fact_check_error = ""
if "manual_video_fact_check_url" not in st.session_state:
    st.session_state.manual_video_fact_check_url = ""
if "manual_video_fact_check_applied_task_id" not in st.session_state:
    st.session_state.manual_video_fact_check_applied_task_id = ""
if "manual_video_fact_check_note" not in st.session_state:
    st.session_state.manual_video_fact_check_note = ""
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
        "deepseek-ai/DeepSeek-V4-Flash",
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

def _fact_check_state_key(prefix: str, field_name: str) -> str:
    return f"{prefix}_{field_name}"


def reset_video_fact_check_state(prefix: str = "video_fact_check") -> None:
    st.session_state[_fact_check_state_key(prefix, "task_id")] = ""
    st.session_state[_fact_check_state_key(prefix, "status")] = "idle"
    st.session_state[_fact_check_state_key(prefix, "error")] = ""
    st.session_state[_fact_check_state_key(prefix, "url")] = ""
    st.session_state[_fact_check_state_key(prefix, "applied_task_id")] = ""
    st.session_state[_fact_check_state_key(prefix, "note")] = ""
    st.session_state[_fact_check_state_key(prefix, "success_toast_task_id")] = ""
    st.session_state[_fact_check_state_key(prefix, "shown_success_toast_task_id")] = ""


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
        )
    )

# --- 后台硬编码/环境变量配置 (对外隐藏设置) ---
proxy_input = os.environ.get("PROXY_URL", st.session_state.settings.get("proxy", ""))
# On Windows, prefer the configured system proxy when no explicit proxy is set.
use_system_proxy = (os.name == "nt") and (not str(proxy_input or "").strip())
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
page_param = str(query_params.get("page", "") or "").strip().lower()
ext_payload_id = str(query_params.get("ext_payload_id", "") or "").strip()
ext_source_url = str(query_params.get("ext_source_url", "") or "").strip()
ext_transcript = str(query_params.get("ext_transcript", "") or "").strip()
ext_autosubmit = str(query_params.get("ext_autosubmit", "") or "").strip().lower() in {"1", "true", "yes"}
ext_route = str(query_params.get("ext_route", "") or "").strip().lower()
bridge_payload_waiting = False
bridge_payload_error = ""

if ext_source_url and not st.session_state.manual_source_url:
    st.session_state.manual_source_url = ext_source_url
    st.session_state.prefer_paste_tab = True

if ext_source_url:
    st.session_state.current_video_url = ext_source_url

auto_fetch_signature = f"{ext_route}|{ext_source_url}"
if (
    ext_source_url
    and ext_autosubmit
    and not ext_payload_id
    and ext_route in {"server_direct", "local_direct", "extension"}
    and st.session_state.video_auto_fetch_last_signature != auto_fetch_signature
):
    st.session_state.video_auto_fetch_pending = True
    st.session_state.video_auto_fetch_url = ext_source_url
    st.session_state.video_auto_fetch_route = ext_route
    st.session_state.video_auto_fetch_last_signature = auto_fetch_signature

if ext_payload_id and st.session_state.manual_last_payload_id != ext_payload_id:
    # 新一轮扩展导入开始时先清掉上一轮 bridge 元信息，避免残留“本地节点/兜底”说明。
    st.session_state.manual_bridge_meta = {}

if ext_payload_id and st.session_state.manual_last_payload_id != ext_payload_id and not ext_transcript:
    bridge_payload, bridge_payload_error = wait_for_extension_bridge_payload(ext_payload_id)
    if not bridge_payload:
        bridge_payload = read_extension_bridge_payload(ext_payload_id, consume=True)
    normalized_bridge_payload = normalize_extension_bridge_payload(bridge_payload)
    bridge_transcript = str(normalized_bridge_payload.get("transcript_text") or "").strip()
    if bridge_transcript:
        ext_transcript = bridge_transcript
        ext_source_url = str(normalized_bridge_payload.get("source_url") or ext_source_url).strip()
        st.session_state.last_transcript_acquisition_path = "extension_bridge_payload"
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
    st.session_state.last_transcript_acquisition_path = "extension_bridge_payload"
    st.session_state.manual_source_url = ext_source_url
    st.session_state.manual_transcript_text = ext_transcript
    st.session_state.manual_summary_text = ""
    st.session_state.manual_summary_duration = {}
    reset_video_fact_check_state("manual_video_fact_check")
    st.session_state.prefer_paste_tab = True
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
    if ext_autosubmit:
        st.session_state.manual_auto_payload_id = ext_payload_id

video_extension_payload_id = st.session_state.get("video_extension_payload_id") or ""
video_extension_last_payload_id = st.session_state.get("video_extension_last_payload_id") or ""
if video_extension_payload_id and video_extension_payload_id != video_extension_last_payload_id:
    video_bridge_payload, video_bridge_payload_error = wait_for_extension_bridge_payload(video_extension_payload_id)
    if not video_bridge_payload:
        video_bridge_payload = read_extension_bridge_payload(video_extension_payload_id, consume=True)
    normalized_video_bridge_payload = normalize_extension_bridge_payload(video_bridge_payload)
    video_bridge_transcript = str(normalized_video_bridge_payload.get("transcript_text") or "").strip()
    if video_bridge_transcript:
        st.session_state.last_transcript_acquisition_path = "extension_bridge_payload"
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


def render_privacy_policy_page():
    st.title("隐私权政策")
    st.caption("YouTube Transcript Helper / YouTube Summarizer")

    st.markdown(
        """
生效日期：2026 年 6 月 15 日

本隐私权政策说明 YouTube Transcript Helper 浏览器扩展和 YouTube Summarizer 主站如何处理用户数据。

### 我们收集或处理的数据

当用户主动使用扩展或主站功能时，产品可能会处理以下数据：

- YouTube 视频链接
- YouTube 视频标题
- YouTube 视频页面中公开可用的字幕文本 transcript
- 用户粘贴到主站中的文本内容
- 为生成摘要、整理要点和辅助事实核查所需的处理结果
- 扩展配置和任务状态，例如总结站点地址、最近一次流程状态，这些数据主要保存在浏览器本地或服务端临时任务记录中

我们不会主动收集以下类型的数据：

- 身份证件、密码、验证码或付款信息
- 健康信息
- 精确地理位置
- 与字幕提取和总结功能无关的网站内容
- 用户的完整浏览历史

### 数据用途

我们仅将上述数据用于以下用途：

- 从 YouTube 视频中提取公开可用的字幕文本
- 将 transcript 发送到总结服务，用于生成摘要、要点整理和事实核查
- 展示任务状态、处理结果和错误提示
- 改善扩展和主站的稳定性与用户体验

### 数据共享

我们不会出售用户数据。

为了完成摘要和事实核查功能，用户提交的 transcript、视频链接或文本内容可能会发送到产品后端服务，以及用于文本生成或检索的第三方 API 服务。我们只会在实现产品核心功能所必需的范围内传输这些数据。

### 数据保存

扩展配置通常保存在用户浏览器本地。主站和桥接服务可能会临时保存 transcript、摘要结果或任务状态，用于完成当前请求、展示结果、排查错误和避免重复处理。我们会避免保存与产品功能无关的数据。

### 用户控制

用户可以通过以下方式控制数据：

- 不点击扩展或不提交链接时，扩展不会主动发送 transcript 到总结服务
- 可以在浏览器扩展管理页面移除扩展
- 可以清除浏览器本地存储和站点数据
- 如需删除服务端相关记录，可以通过下方联系方式提出请求

### 权限说明

扩展请求的权限仅用于实现字幕提取和总结流程：

- activeTab：在用户主动点击扩展后访问当前 YouTube 标签页
- scripting：向当前页面注入脚本以读取字幕相关数据
- tabs：读取当前标签页标题和 URL，并在用户点击时打开总结页面
- clipboardWrite：在用户点击复制时写入剪贴板
- storage：保存扩展配置和任务状态
- YouTube 和产品服务域名权限：读取 YouTube 字幕并与总结服务通信

### 联系方式

如对隐私政策或数据删除有疑问，请通过项目页面或 Chrome Web Store 支持入口联系我们。

### 政策更新

我们可能会根据产品功能、部署方式或合规要求更新本隐私权政策。更新后的内容会发布在本页面。
        """
    )



if page_param in {"privacy", "privacy-policy"}:
    render_privacy_policy_page()
    st.stop()

# --- 主界面 ---
st.title(t("main_title"))
st.caption(t("main_caption"))
admin_mode = is_admin_user()

# Lite 一级导航：突出立即总结，其他能力下沉。
tab_home, tab_history, tab_wishwall, tab_settings = st.tabs([
    t("tab_home"),
    t("tab_history"),
    t("tab_wishwall"),
    t("tab_settings"),
])

# --- 通用逻辑函数 (供两个 Tab 使用) ---
def fetch_transcript_via_shared_service(video_url, progress_callback=None):
    """主站输入和插件失败兜底共用的服务端字幕抓取链路，不启用本地转写。"""
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
        setattr(api, "_asr_enabled", False)
        setattr(api, "_disable_audio_transcribe_override", True)
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
        st.session_state.last_transcript_acquisition_path = "shared_service_no_asr"
        return text, None
    except Exception as e:
        return None, format_error(e)


def internal_fetch_transcript(video_url, progress_callback=None):
    """
    核心抓取逻辑，返回 (transcript_text, error_msg)。
    当前仅代理到统一服务端字幕链路，供主站输入和插件失败兜底复用。
    """
    return fetch_transcript_via_shared_service(video_url, progress_callback)

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
        eff_proxy = (
            str(proxy_override or "").strip()
            if proxy_override is not None
            else get_effective_proxy(proxy_input, use_system_proxy)[0]
        )
        
        # --- 限流检查 ---
        client_ip = get_client_ip()
        is_owner = rate_limiter.is_owner(st.session_state.settings)
        if not is_owner:
            allowed, msg = rate_limiter.check_limit(client_ip)
            if not allowed:
                return None, msg

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
            summary = _call_with_optional_kwargs(
                summarize_text,
                text,
                eff_api_key,
                eff_base_url,
                summary_model_name,
                eff_proxy,
                fact_check_model=fact_check_model_name,
                enable_fact_check=enable_fact_check,
                ui_locale=get_ui_locale(),
                stream=False  # 后台任务默认不使用流式
            )
            summary_text = str(summary or "").strip()
            if not summary_text:
                return None, "总结结果为空，请稍后重试"
            if summary_text.startswith("总结失败：") or summary_text.startswith("请填写 API Key"):
                return None, summary_text
            
            # 总结成功，增加限流计数
            if not is_owner:
                rate_limiter.increment(client_ip)
                
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
            "video_fact_check_v3",
            str(url or "").strip(),
            str(summary_markdown or "").strip()[:2500],
            str(transcript_text or "").strip()[:5000],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def start_video_fact_check_async(
    url: str,
    transcript_text: str,
    summary_content: str,
    *,
    summary_state_key: str = "summary_text",
    state_prefix: str = "video_fact_check",
    history_entry_state_key: str = "video_history_entry_id",
) -> None:
    summary_md, _fact_md = _parse_summary_for_ui(summary_content)
    transcript_value = str(transcript_text or "").strip()
    url_value = str(url or "").strip()
    if not summary_md or not transcript_value or not api_key:
        reset_video_fact_check_state(state_prefix)
        return

    runtime = _get_video_fact_check_runtime()
    plan = decide_video_fact_check_plan(transcript_value, summary_md)
    print(
        "VideoFactCheckPlan: "
        f"state_prefix={state_prefix}, "
        f"url={url_value}, should_fact_check={bool(plan.get('should_fact_check'))}, "
        f"reason={str(plan.get('reason') or '').strip()}, "
        f"recommended_claim_count={int(plan.get('recommended_claim_count') or 0)}"
    , flush=True)
    if not bool(plan.get("should_fact_check")):
        reset_video_fact_check_state(state_prefix)
        st.session_state[_fact_check_state_key(state_prefix, "status")] = "skipped"
        st.session_state[_fact_check_state_key(state_prefix, "note")] = str(plan.get("reason") or "").strip()
        st.session_state[_fact_check_state_key(state_prefix, "url")] = url_value
        return

    planned_claims = int(plan.get("recommended_claim_count") or 3)
    max_claims = max(1, min(3, planned_claims))
    fast_claims = max_claims
    plan_note = str(plan.get("reason") or "").strip()
    if planned_claims > max_claims:
        plan_note = f"为控制等待时间，本轮先快速核查最重要的 {max_claims} 条声明；其余声明暂不自动深度补跑。"
    cache_key = _build_video_fact_check_cache_key(url_value, summary_md, transcript_value)

    with runtime["lock"]:
        cached_result = str((runtime.get("result_cache") or {}).get(cache_key) or "").strip()
    if cached_result:
        st.session_state[summary_state_key] = _merge_fact_check_into_summary(summary_content, cached_result)
        update_history_entry_summary(
            st.session_state.get(history_entry_state_key),
            st.session_state[summary_state_key],
        )
        cache_task_id = f"{state_prefix}_cache_{cache_key[:12]}"
        st.session_state[_fact_check_state_key(state_prefix, "task_id")] = cache_task_id
        st.session_state[_fact_check_state_key(state_prefix, "status")] = "success"
        st.session_state[_fact_check_state_key(state_prefix, "error")] = ""
        st.session_state[_fact_check_state_key(state_prefix, "url")] = url_value
        st.session_state[_fact_check_state_key(state_prefix, "applied_task_id")] = cache_task_id
        st.session_state[_fact_check_state_key(state_prefix, "note")] = "新闻核查已命中缓存。"
        return

    task_id = f"video_fact_check_{uuid.uuid4().hex}"

    with runtime["lock"]:
        runtime["tasks"][task_id] = {
            "status": "queued",
            "started_at": time.time(),
            "result": "",
            "error": "",
            "url": url_value,
            "cache_key": cache_key,
            "note": plan_note,
            "result_version": "",
        }

    st.session_state[_fact_check_state_key(state_prefix, "task_id")] = task_id
    st.session_state[_fact_check_state_key(state_prefix, "status")] = "queued"
    st.session_state[_fact_check_state_key(state_prefix, "error")] = ""
    st.session_state[_fact_check_state_key(state_prefix, "url")] = url_value
    st.session_state[_fact_check_state_key(state_prefix, "applied_task_id")] = ""
    st.session_state[_fact_check_state_key(state_prefix, "note")] = plan_note

    eff_api_key = api_key
    eff_base_url = base_url
    eff_proxy = proxy_input
    eff_fact_model = fact_check_model_selected
    eff_ui_locale = get_ui_locale()

    def _worker():
        worker_started_at = time.time()
        with runtime["lock"]:
            task = runtime["tasks"].get(task_id) or {}
            task["status"] = "running"
            task["phase"] = "fast"
            task["started_at"] = float(task.get("started_at") or worker_started_at)
            started_at = float(task["started_at"])
            runtime["tasks"][task_id] = task
        try:
            print(
                f"VideoFactCheckWorker: started fast task_id={task_id} url={url_value} "
                f"fast_claims={fast_claims} max_claims={max_claims}",
                flush=True,
            )
            fast_fact_markdown = _call_with_optional_kwargs(
                fact_check_document_claims,
                text=transcript_value,
                summary_markdown=summary_md,
                api_key=eff_api_key,
                base_url=eff_base_url,
                model=eff_fact_model,
                proxy_url=eff_proxy,
                max_claims=fast_claims,
                ui_locale=eff_ui_locale,
                search_mode="fast",
            )
            with runtime["lock"]:
                runtime["tasks"][task_id] = {
                    "status": "running",
                    "phase": "deep",
                    "started_at": started_at,
                    "result": str(fast_fact_markdown or "").strip(),
                    "result_version": "fast",
                    "error": "",
                    "url": url_value,
                    "cache_key": cache_key,
                    "note": f"快速核查已完成 {fast_claims} 条。",
                }
            if max_claims <= fast_claims:
                fact_markdown = fast_fact_markdown
            else:
                print(f"VideoFactCheckWorker: started deep task_id={task_id} url={url_value} max_claims={max_claims}", flush=True)
                fact_markdown = _call_with_optional_kwargs(
                    fact_check_document_claims,
                    text=transcript_value,
                    summary_markdown=summary_md,
                    api_key=eff_api_key,
                    base_url=eff_base_url,
                    model=eff_fact_model,
                    proxy_url=eff_proxy,
                    max_claims=max_claims,
                    ui_locale=eff_ui_locale,
                    search_mode="deep",
                )
            with runtime["lock"]:
                result_cache = runtime.setdefault("result_cache", {})
                result_cache[cache_key] = str(fact_markdown or "").strip()
                if len(result_cache) > 80:
                    oldest_key = next(iter(result_cache))
                    if oldest_key != cache_key:
                        result_cache.pop(oldest_key, None)
                completed_at = time.time()
                runtime["tasks"][task_id] = {
                    "status": "success",
                    "phase": "done",
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_seconds": completed_at - started_at,
                    "result": str(fact_markdown or "").strip(),
                    "result_version": "deep",
                    "error": "",
                    "url": url_value,
                    "cache_key": cache_key,
                    "note": f"深度核查已完成，约 {max_claims} 条关键声明已刷新。",
                }
            print(f"VideoFactCheckWorker: success deep task_id={task_id} url={url_value}", flush=True)
        except Exception as exc:
            with runtime["lock"]:
                completed_at = time.time()
                runtime["tasks"][task_id] = {
                    "status": "error",
                    "phase": "error",
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_seconds": completed_at - started_at,
                    "result": "",
                    "result_version": "",
                    "error": str(exc),
                    "url": url_value,
                    "cache_key": cache_key,
                    "note": plan_note,
                }
            print(f"VideoFactCheckWorker: error task_id={task_id} url={url_value} error={exc}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()


def sync_video_fact_check_state(
    *,
    summary_state_key: str = "summary_text",
    duration_state_key: str = "summary_duration",
    state_prefix: str = "video_fact_check",
    history_entry_state_key: str = "video_history_entry_id",
) -> None:
    task_id = str(st.session_state.get(_fact_check_state_key(state_prefix, "task_id")) or "").strip()
    if not task_id:
        return

    runtime = _get_video_fact_check_runtime()
    with runtime["lock"]:
        task = dict(runtime["tasks"].get(task_id) or {})

    if not task:
        return

    status = str(task.get("status") or "idle").strip()
    st.session_state[_fact_check_state_key(state_prefix, "status")] = status
    st.session_state[_fact_check_state_key(state_prefix, "error")] = str(task.get("error") or "").strip()
    st.session_state[_fact_check_state_key(state_prefix, "url")] = str(
        task.get("url") or st.session_state.get(_fact_check_state_key(state_prefix, "url")) or ""
    ).strip()
    st.session_state[_fact_check_state_key(state_prefix, "note")] = str(
        task.get("note") or st.session_state.get(_fact_check_state_key(state_prefix, "note")) or ""
    ).strip()
    fact_check_duration = task.get("duration_seconds")
    if isinstance(fact_check_duration, (int, float)) and fact_check_duration > 0:
        duration_info = dict(st.session_state.get(duration_state_key) or {})
        duration_info["fact_check"] = float(fact_check_duration)
        st.session_state[duration_state_key] = duration_info

    result_version = str(task.get("result_version") or ("deep" if status == "success" else "")).strip()
    applied_task_marker = f"{task_id}:{result_version or status}"
    if (
        status in {"running", "success"}
        and result_version
        and st.session_state.get(_fact_check_state_key(state_prefix, "applied_task_id")) != applied_task_marker
        and str(task.get("result") or "").strip()
        and st.session_state.get(summary_state_key)
    ):
        st.session_state[summary_state_key] = _merge_fact_check_into_summary(
            st.session_state[summary_state_key],
            str(task.get("result") or "").strip(),
        )
        update_history_entry_summary(
            st.session_state.get(history_entry_state_key),
            st.session_state[summary_state_key],
        )
        st.session_state[_fact_check_state_key(state_prefix, "applied_task_id")] = applied_task_marker
        st.session_state[_fact_check_state_key(state_prefix, "status")] = status
        if status == "success":
            st.session_state[_fact_check_state_key(state_prefix, "success_toast_task_id")] = applied_task_marker

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
        ui_locale = get_ui_locale()
        def relay_document_progress(pct, message):
            if progress_callback:
                progress_callback(25 + int(min(max(pct, 0), 100) * 0.45), message)

        summary_result = _call_with_optional_kwargs(
            summarize_document_text,
            extracted["clean_text"],
            eff_api_key,
            eff_base_url,
            summary_model_name,
            eff_proxy,
            progress_callback=relay_document_progress,
            ui_locale=ui_locale,
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

            fact_check_markdown = _call_with_optional_kwargs(
                fact_check_document_claims,
                text=extracted["clean_text"],
                summary_markdown=summary_result["summary_markdown"],
                api_key=eff_api_key,
                base_url=eff_base_url,
                model=fact_check_model_name,
                proxy_url=eff_proxy,
                max_claims=int(fact_check_plan.get("recommended_claim_count") or 5),
                progress_callback=relay_fact_progress,
                ui_locale=ui_locale,
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
        eff_proxy = (
            str(proxy_override or "").strip()
            if proxy_override is not None
            else get_effective_proxy(proxy_input, use_system_proxy)[0]
        )
        summary_model_name = str(model_name or summary_model_selected).strip() or summary_model_selected
        fact_check_model_name = fact_check_model_selected

        # --- 限流检查 ---
        client_ip = get_client_ip()
        is_owner = rate_limiter.is_owner(st.session_state.settings)
        if not is_owner:
            allowed, msg = rate_limiter.check_limit(client_ip)
            if not allowed:
                return None, msg

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
        res = run_document_summary_pipeline(
            extracted,
            summary_model_name,
            fact_check_model_name,
            eff_api_key,
            eff_base_url,
            eff_proxy,
            progress_callback=progress_callback,
        )
        
        # 总结成功，增加限流计数
        if not is_owner:
            rate_limiter.increment(client_ip)
            
        return res, None


def internal_summarize_document_url(source_url, model_name, progress_callback=None, api_key_override=None, base_url_override=None, proxy_override=None):
        eff_api_key = api_key_override or api_key
        eff_base_url = base_url_override or base_url
        eff_proxy = (
            str(proxy_override or "").strip()
            if proxy_override is not None
            else get_effective_proxy(proxy_input, use_system_proxy)[0]
        )
        summary_model_name = str(model_name or summary_model_selected).strip() or summary_model_selected
        fact_check_model_name = fact_check_model_selected

        # --- 限流检查 ---
        client_ip = get_client_ip()
        is_owner = rate_limiter.is_owner(st.session_state.settings)
        if not is_owner:
            allowed, msg = rate_limiter.check_limit(client_ip)
            if not allowed:
                return None, msg

        if not eff_api_key:
            return None, "请先填写 API Key。"
        if progress_callback:
            progress_callback(10, "正在抓取在线文档/网页...")

        extracted = extract_document_from_url(source_url, proxy_url=eff_proxy)
        if progress_callback:
            progress_callback(25, f"在线内容解析完成，正文约 {extracted['char_count']} 字符。")
        res = run_document_summary_pipeline(
            extracted,
            summary_model_name,
            fact_check_model_name,
            eff_api_key,
            eff_base_url,
            eff_proxy,
            progress_callback=progress_callback,
        )
        
        # 总结成功，增加限流计数
        if not is_owner:
            rate_limiter.increment(client_ip)
            
        return res, None


# ==========================
# ====== 新增：后台任务状态轮询 ======
# ==========================
import time
from task_runner import submit_task, get_task_status

if "bg_task_id" not in st.session_state:
    st.session_state.bg_task_id = None

def render_background_task_status_panel():
    """
    读取当前后台任务状态，并返回任务 ID 与状态信息。

    注意：这里不要做全局的 sleep/rerun 轮询，否则整个页面会被频繁重刷，
    Streamlit Tabs 会不断回到默认页，用户很难切到“任务中心”查看详情。
    """
    current_bg_task_id = st.session_state.bg_task_id or ""
    current_bg_task_status = None

    if st.session_state.bg_task_id:
        task_id = st.session_state.bg_task_id
        status_info = get_task_status(task_id)
        current_bg_task_status = status_info

    current_processing_task = st.session_state.get("current_processing_task") or {}
    processing_status = str(current_processing_task.get("status") or "").strip()
    if (
        not current_bg_task_status
        and current_processing_task
        and processing_status in {"queued", "running", "success", "failed"}
    ):
        current_bg_task_id = str(current_processing_task.get("task_id") or "").strip()
        current_bg_task_status = current_processing_task

    return current_bg_task_id, current_bg_task_status
# ====== 新增结束 ======


def _update_current_processing_task(
    *,
    task_id: str = "",
    url: str = "",
    status: str = "",
    source: str = "处理中心",
    title: str = "",
    error: str = "",
    result: str = "",
    note: str = "",
):
    existing = st.session_state.get("current_processing_task") or {}
    normalized_task_id = str(task_id or existing.get("task_id") or "").strip()
    normalized_url = str(url or existing.get("url") or "").strip()
    created_at = str(existing.get("created_at") or "").strip()
    if normalized_task_id and normalized_task_id != str(existing.get("task_id") or "").strip():
        created_at = _iso(_now())
    if not created_at:
        created_at = _iso(_now())
    st.session_state.current_processing_task = {
        "task_id": normalized_task_id,
        "url": normalized_url,
        "status": str(status or existing.get("status") or "").strip(),
        "source": str(source or existing.get("source") or t("task_source_center")).strip() or t("task_source_center"),
        "title": str(title or existing.get("title") or normalized_url or t("task_current_title")).strip() or t("task_current_title"),
        "error": str(error or "").strip(),
        "result": str(result or existing.get("result") or ""),
        "note": str(note or "").strip(),
        "created_at": created_at,
    }


def _clear_current_processing_task():
    st.session_state.current_processing_task = {}

def _task_center_status_label(status: str) -> str:
    status_map = {
        "queued": t("status_queued"),
        "running": t("status_running"),
        "success": t("status_success"),
        "failed": t("status_failed"),
        "partial": t("status_partial"),
        "no_update": t("status_no_update"),
        "not_found": t("status_expired"),
    }
    return status_map.get(str(status or "").strip(), t("status_unknown"))


def _task_center_source_label(source: str) -> str:
    normalized = str(source or "").strip()
    source_map = {
        "自动任务": t("task_source_auto"),
        "处理中心": t("task_source_center"),
        "失败重试": t("task_source_retry"),
        "处理中心失败重试": t("task_source_center_retry"),
    }
    return source_map.get(normalized, normalized)


def _task_center_status_icon(status: str) -> str:
    status_map = {
        "queued": "⏳",
        "running": "🔄",
        "success": "✅",
        "failed": "❌",
        "partial": "🟡",
        "no_update": "🟦",
        "not_found": "⚪",
    }
    return status_map.get(str(status or "").strip(), "❔")


def _format_task_center_time(value: str) -> str:
    dt_value = _parse_iso(value)
    if not dt_value:
        return "—"
    return dt_value.strftime("%m-%d %H:%M")


def _build_task_center_records(current_bg_task_id, current_bg_task_status, task_run_items):
    records = []

    for item in task_run_items:
        if not isinstance(item, dict):
            continue
        record_id = f"scheduled:{item.get('run_id') or ''}:{item.get('video_id') or ''}:{item.get('created_at') or ''}"
        records.append({
            "record_id": record_id,
            "task_id": "",
            "kind": "scheduled_run_item",
            "source": t("task_source_auto"),
            "status": str(item.get("status") or "").strip() or "failed",
            "title": str(item.get("title") or t("task_unnamed")).strip(),
            "url": str(item.get("url") or "").strip(),
            "channel_name": str(item.get("channel_name") or "").strip(),
            "created_at": str(item.get("created_at") or "").strip(),
            "duration_seconds": int(item.get("duration_seconds") or 0),
            "summary": str(item.get("summary") or ""),
            "error": str(item.get("error") or "").strip(),
            "can_retry": bool(str(item.get("url") or "").strip()),
        })

    if current_bg_task_id and current_bg_task_status:
        records.append({
            "record_id": f"processing:{current_bg_task_id}",
            "task_id": current_bg_task_id,
            "kind": "processing_center",
            "source": t("task_source_center"),
            "status": str(current_bg_task_status.get("status") or "unknown").strip(),
            "title": str(current_bg_task_status.get("url") or t("task_current_bg_title")).strip() or t("task_current_bg_title"),
            "url": str(current_bg_task_status.get("url") or "").strip(),
            "channel_name": "",
            "created_at": "",
            "duration_seconds": 0,
            "summary": str(current_bg_task_status.get("result") or ""),
            "error": str(current_bg_task_status.get("error") or "").strip(),
            "can_retry": bool(str(current_bg_task_status.get("url") or "").strip()),
        })

    retry_jobs = st.session_state.get("task_center_retry_jobs") or []
    normalized_retry_jobs = []
    for job in retry_jobs:
        if not isinstance(job, dict):
            continue
        task_id = str(job.get("task_id") or "").strip()
        if not task_id:
            continue
        live_status = get_task_status(task_id)
        normalized_job = dict(job)
        normalized_job["status"] = str(live_status.get("status") or "unknown").strip()
        normalized_job["result"] = str(live_status.get("result") or normalized_job.get("result") or "")
        normalized_job["error"] = str(live_status.get("error") or normalized_job.get("error") or "").strip()
        normalized_retry_jobs.append(normalized_job)
        if task_id == current_bg_task_id:
            continue
        records.append({
            "record_id": f"retry:{task_id}",
            "task_id": task_id,
            "kind": "retry_task",
            "source": t("task_source_retry"),
            "status": normalized_job["status"],
            "title": str(normalized_job.get("title") or normalized_job.get("url") or t("task_source_retry")).strip(),
            "url": str(normalized_job.get("url") or "").strip(),
            "channel_name": str(normalized_job.get("channel_name") or "").strip(),
            "created_at": str(normalized_job.get("created_at") or "").strip(),
            "duration_seconds": 0,
            "summary": normalized_job["result"],
            "error": normalized_job["error"],
            "can_retry": bool(str(normalized_job.get("url") or "").strip()),
        })
    st.session_state.task_center_retry_jobs = normalized_retry_jobs[-50:]

    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return records


def _task_center_record_matches(record, status_filter, source_filter, keyword):
    status_value = str(record.get("status") or "").strip()
    if status_filter != t("filter_all"):
        status_label = _task_center_status_label(status_value)
        if status_filter != status_label:
            return False
    if source_filter != t("filter_all"):
        if str(record.get("source") or "").strip() != source_filter:
            return False
    keyword = str(keyword or "").strip().lower()
    if not keyword:
        return True
    haystack = "\n".join([
        str(record.get("title") or ""),
        str(record.get("url") or ""),
        str(record.get("channel_name") or ""),
        str(record.get("source") or ""),
        str(record.get("error") or ""),
    ]).lower()
    return keyword in haystack


def _submit_task_center_retry(url: str, *, title: str = "", channel_name: str = "", source: str = ""):
    retry_task_id = submit_task(
        url,
        summary_model_selected,
        fact_check_model_selected,
        proxy_input,
        use_system_proxy,
        api_key,
        base_url,
        get_ui_locale(),
    )
    retry_jobs = st.session_state.get("task_center_retry_jobs") or []
    retry_jobs.append({
        "task_id": retry_task_id,
        "url": str(url or "").strip(),
        "title": str(title or "").strip(),
        "channel_name": str(channel_name or "").strip(),
        "source": str(source or t("task_source_retry")).strip() or t("task_source_retry"),
        "created_at": _iso(_now()),
        "result": "",
        "error": "",
        "status": "queued",
    })
    st.session_state.task_center_retry_jobs = retry_jobs[-50:]
    return retry_task_id


def render_task_center_metrics(task_defs, records, task_runs):
    """
    渲染任务中心顶部指标栏。
    """
    running_count = len([item for item in records if str(item.get("status") or "") in {"queued", "running"}])
    failed_count = len([item for item in records if str(item.get("status") or "") == "failed"])
    success_count = len([item for item in records if str(item.get("status") or "") == "success"])
    total_finished = success_count + failed_count
    success_rate = int((success_count / total_finished) * 100) if total_finished else 0
    last_7d_runs = [
        run for run in task_runs
        if _parse_iso(run.get("triggered_at")) and _parse_iso(run.get("triggered_at")) >= (_now() - timedelta(days=7))
    ]

    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
    metric_col1.metric(t("task_metric_running"), running_count)
    metric_col2.metric(t("task_metric_failed"), failed_count)
    metric_col3.metric(t("task_metric_success"), success_count)
    metric_col4.metric(t("task_metric_configured"), len(task_defs))
    metric_col5.metric(t("task_metric_success_rate_7d"), f"{success_rate}%")

    st.caption(t("task_overview", running=running_count, success=success_count, failed=failed_count, runs=len(last_7d_runs)))


def render_current_bg_task_panel(current_bg_task_id, current_bg_task_status, *, key_prefix: str = "task_center"):
    """
    渲染当前后台任务状态面板。
    """
    if not current_bg_task_status:
        st.info(t("task_center_no_bg"))
        return

    status_label_map = {
        "queued": t("status_queued"),
        "running": t("status_running"),
        "success": t("status_success_done"),
        "failed": t("status_failed"),
    }
    with st.container(border=True):
        current_status = str(current_bg_task_status.get("status") or "unknown").strip()
        st.markdown(f"**{t('task_center_task_id')}**：`{current_bg_task_id[:8]}`")
        st.caption(f"{t('task_center_status')}：`{status_label_map.get(current_status, current_status or t('status_unknown'))}`")
        task_note = str(current_bg_task_status.get("note") or "").strip()
        if task_note:
            st.caption(task_note)

        if current_status == "success":
            st.success(t("task_center_done"))
            result_text = str(current_bg_task_status.get("result") or "").strip()
            if result_text:
                with st.expander(t("task_center_view_result"), expanded=False):
                    st.write(result_text)
        elif current_status == "failed":
            st.error(t("task_center_failed", error=current_bg_task_status.get("error", t("status_unknown"))))
            retry_url = str(current_bg_task_status.get("url") or "").strip()
            if retry_url:
                if st.button(t("task_center_retry_current"), key="task_center_retry_current_bg", use_container_width=True):
                    retry_task_id = _submit_task_center_retry(
                        retry_url,
                        title=retry_url,
                        source=t("task_source_center_retry"),
                    )
                    st.toast(t("task_center_retry_resubmitted", task_id=retry_task_id[:8]), icon="🔄")
                    st.rerun()
        else:
            st.info(t("task_center_running_info"))

        action_col1, action_col2 = st.columns([1, 1])
        with action_col1:
            if st.button(t("task_center_clear"), key=f"{key_prefix}_clear_bg", use_container_width=True):
                st.session_state.bg_task_id = None
                _clear_current_processing_task()
                st.rerun()
        with action_col2:
            if st.button(t("task_center_refresh"), key=f"{key_prefix}_refresh_bg", use_container_width=True):
                st.rerun()


def render_task_center_filters(records):
    status_options = [t("filter_all"), t("status_queued"), t("status_running"), t("status_success"), t("status_failed")]
    source_options = ["全部"] + sorted({str(item.get("source") or "").strip() for item in records if str(item.get("source") or "").strip()})
    source_options = [t("filter_all")] + sorted({str(item.get("source") or "").strip() for item in records if str(item.get("source") or "").strip()})

    filter_col1, filter_col2, filter_col3 = st.columns([1.1, 1.1, 2.2])
    with filter_col1:
        status_filter = st.selectbox(t("task_filter_status"), status_options, key="task_center_status_filter")
    with filter_col2:
        source_filter = st.selectbox(t("task_filter_source"), source_options, key="task_center_source_filter")
    with filter_col3:
        keyword = st.text_input(t("task_filter_search"), key="task_center_keyword", placeholder=t("task_filter_search_placeholder"))

    filtered_records = [
        item for item in records
        if _task_center_record_matches(item, status_filter, source_filter, keyword)
    ]
    st.caption(t("task_filter_summary", total=len(records), filtered=len(filtered_records)))
    return filtered_records


def render_task_center_batch_actions(records):
    failed_candidates = [
        item for item in records
        if str(item.get("status") or "") == "failed" and str(item.get("url") or "").strip()
    ]
    if not failed_candidates:
        st.caption(t("task_batch_no_failed"))
        return

    option_map = {item["record_id"]: item for item in failed_candidates}
    selected_ids = st.multiselect(
        t("task_batch_select"),
        options=list(option_map.keys()),
        default=st.session_state.get("task_center_batch_retry_ids") or [],
        format_func=lambda record_id: (
            f"{option_map[record_id].get('title') or t('task_unnamed')}"
            f" | {_task_center_source_label(option_map[record_id].get('source'))}"
            f" | {_format_task_center_time(option_map[record_id].get('created_at') or '')}"
        ),
        key="task_center_batch_retry_ids",
    )

    action_col1, action_col2 = st.columns([1, 1])
    with action_col1:
        if st.button(t("task_batch_select_all"), use_container_width=True, key="task_center_select_all_failed"):
            st.session_state.task_center_batch_retry_ids = list(option_map.keys())
            st.rerun()
    with action_col2:
        if st.button(t("task_batch_retry"), type="primary", use_container_width=True, key="task_center_batch_retry_submit"):
            if not selected_ids:
                st.warning(t("task_batch_select_warning"))
            else:
                submitted_count = 0
                for record_id in selected_ids:
                    item = option_map.get(record_id)
                    if not item:
                        continue
                    retry_url = str(item.get("url") or "").strip()
                    if not retry_url:
                        continue
                    _submit_task_center_retry(
                        retry_url,
                        title=str(item.get("title") or "").strip(),
                        channel_name=str(item.get("channel_name") or "").strip(),
                    )
                    submitted_count += 1
                st.session_state.task_center_batch_retry_ids = []
                st.toast(t("task_batch_submitted", count=submitted_count), icon="🚀")
                st.rerun()


def render_recent_task_run_item(item):
    """
    渲染单条最近执行记录。
    """
    with st.container(border=True):
        head_c1, head_c2 = st.columns([4, 1])
        with head_c1:
            item_title = str(item.get("title") or t("task_unnamed")).strip()
            st.markdown(f"**{item_title}**")
            meta_parts = []
            if item.get("channel_name"):
                meta_parts.append(f"{t('task_meta_channel')}：{item.get('channel_name')}")
            if item.get("created_at"):
                meta_parts.append(f"{t('task_meta_time')}：{_format_task_center_time(item.get('created_at'))}")
            if item.get("url"):
                meta_parts.append(f"[{t('task_meta_link')}]({item.get('url')})")
            if item.get("source"):
                meta_parts.append(f"{t('task_meta_source')}：{_task_center_source_label(item.get('source'))}")
            if meta_parts:
                st.caption(" | ".join(meta_parts))
        with head_c2:
            status_value = str(item.get("status") or "").strip()
            status_label = _task_center_status_label(status_value)
            if status_value == "success":
                st.success(status_label, icon=_task_center_status_icon(status_value))
            elif status_value in {"queued", "running"}:
                st.info(status_label, icon=_task_center_status_icon(status_value))
            else:
                st.error(status_label, icon=_task_center_status_icon(status_value))

        detail_parts = []
        if item.get("task_id"):
            detail_parts.append(f"{t('task_meta_task_id')}：`{str(item.get('task_id'))[:8]}`")
        if item.get("duration_seconds"):
            detail_parts.append(f"{t('task_meta_duration')}：{int(item.get('duration_seconds') or 0)}s")
        if detail_parts:
            st.caption(" | ".join(detail_parts))

        if item.get("status") == "success":
            with st.expander(t("task_result_expander"), expanded=False):
                summary_content = item.get("summary") or ""
                if summary_content:
                    render_summary_content(summary_content, fact_title=t("video_fact_check_title"))
                else:
                    st.markdown(t("task_result_empty"))
        else:
            st.caption(t("task_failure_reason", error=item.get("error") or t("status_unknown")))

        if item.get("status") == "failed" and item.get("can_retry"):
            retry_url = str(item.get("url") or "").strip()
            if st.button(t("task_retry_single"), key=f"task_center_retry_{item.get('record_id')}", use_container_width=True):
                retry_task_id = _submit_task_center_retry(
                    retry_url,
                    title=item_title,
                    channel_name=str(item.get("channel_name") or "").strip(),
                )
                st.toast(t("task_center_retry_resubmitted", task_id=retry_task_id[:8]), icon="🔄")
                st.rerun()


def render_recent_task_runs_panel(records):
    """
    渲染任务记录列表。
    """
    if not records:
        st.caption(t("task_records_empty"))
        return

    recent_items = sorted(records, key=lambda item: item.get("created_at") or "", reverse=True)[:30]
    for item in recent_items:
        render_recent_task_run_item(item)


def render_task_logs_panel(task_logs):
    """
    渲染任务运行日志。
    """
    if task_logs:
        st.dataframe(task_logs[-50:], use_container_width=True, hide_index=True)
    else:
        st.caption(t("task_logs_empty"))


def render_task_center_page(current_bg_task_id, current_bg_task_status, *, show_header: bool = True):
    """
    渲染任务中心页面，统一展示后台异步任务、最近执行记录与运行日志。
    """
    if show_header:
        st.markdown(t("task_center_header"))
        st.caption(t("task_center_caption"))

    _task_settings, task_defs, task_logs, task_runs, task_run_items, _task_processed_ids = _load_scheduled_state()
    records = _build_task_center_records(current_bg_task_id, current_bg_task_status, task_run_items)

    render_task_center_metrics(task_defs, records, task_runs)
    current_task_tab, recent_runs_tab, logs_tab = st.tabs([t("task_tab_current"), t("task_tab_list"), t("task_tab_logs")])

    with current_task_tab:
        render_current_bg_task_panel(current_bg_task_id, current_bg_task_status, key_prefix="task_center")

    with recent_runs_tab:
        filtered_records = render_task_center_filters(records)
        st.divider()
        render_task_center_batch_actions(filtered_records)
        st.divider()
        render_recent_task_runs_panel(filtered_records)

    with logs_tab:
        render_task_logs_panel(task_logs)

    task_status_value = (current_bg_task_status or {}).get("status") or "idle"
    return task_status_value, task_logs, task_runs, task_run_items


def render_library_filters(history_count: int):
    """
    渲染资产库筛选栏。
    """
    filter_col1, filter_col2, filter_col3 = st.columns([4.2, 0.8, 1.2])
    with filter_col1:
        hist_kw = st.text_input(t("history_search_label"), key="hist_kw")
    with filter_col2:
        search_body = st.checkbox(t("history_search_fulltext"), value=True)
    with filter_col3:
        if history_count > 0 and is_admin_user():
            if st.button(t("history_clear"), use_container_width=True):
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
        st.caption(
            t(
                "history_entry_caption",
                source=t("history_source_schedule") if entry.get("source_type") == "schedule" else t("history_source_single"),
                url=entry.get("video_url") or "",
            )
        )

        render_summary_content(
            entry.get("summary_text") or "",
            fact_title=t("video_fact_check_title"),
        )


def render_library_page(*, show_header: bool = True):
    """
    渲染内容资产库，统一浏览历史摘要与全文检索结果。
    """
    if show_header:
        st.markdown(t("history_header"))
        st.caption(t("history_caption"))

    if is_admin_user():
        history = load_history() or []
    else:
        history = get_session_history() or []
    if history:
        try:
            st.download_button(
                t("history_export"),
                data=json.dumps(history, ensure_ascii=False, indent=2),
                file_name="youtube_summarizer_history.json",
                mime="application/json",
                use_container_width=False,
                key="btn_export_history",
            )
        except Exception:
            pass
    hist_kw, search_body = render_library_filters(len(history))

    if not history:
        st.info(t("history_empty"))
        return

    matched_entries = [
        entry for entry in history
        if history_entry_matches(entry, hist_kw, search_body)
    ]
    st.caption(t("history_count", total=len(history), matched=len(matched_entries)))

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
        runtime_summary = "Local Dev" if get_ui_locale() == "en" and "expected_commit=latest-local" in runtime_diag else "本地开发版" if "expected_commit=latest-local" in runtime_diag else t("status_running")
        runtime_caption = f"commit={render_info['commit_short'] or 'local'} | deploy=local"
    task_summary = t("status_running") if task_status_value in ["queued", "running"] else t("status_idle")
    bridge_summary = "Connected" if get_ui_locale() == "en" and st.session_state.manual_bridge_meta else "已连接" if st.session_state.manual_bridge_meta else "Not yet" if get_ui_locale() == "en" else "暂无"

    diag_col1, diag_col2, diag_col3 = st.columns(3)

    with diag_col1:
        with st.container(border=True):
            st.caption(t("settings_metric_runtime"))
            st.markdown(f"### {runtime_summary}")
            st.caption(runtime_caption)

    with diag_col2:
        with st.container(border=True):
            st.caption(t("settings_metric_bg"))
            st.markdown(f"### {task_summary}")
            st.caption(t("settings_metric_bg_caption"))

    with diag_col3:
        with st.container(border=True):
            st.caption(t("settings_metric_bridge"))
            st.markdown(f"### {bridge_summary}")
            st.caption(t("settings_metric_bridge_caption"))

    with st.expander(t("settings_runtime_detail"), expanded=False):
        if runtime_lines:
            st.code("\n".join(runtime_lines), language="text")
        else:
            st.caption(t("settings_runtime_detail_empty"))

    with st.expander(t("settings_render_detail"), expanded=False):
        if render_info["is_render"] == "yes":
            st.json(
                {
                    "commit": render_info["commit"] or "unknown",
                    "branch": render_info["branch"] or "unknown",
                    "deploy_id": render_info["deploy_id"] or t("settings_render_deploy_hidden"),
                    "service_id": render_info["service_id"] or "unknown",
                    "service_name": render_info["service_name"] or "unknown",
                    "service_type": render_info["service_type"] or "unknown",
                    "external_url": render_info["external_url"] or "",
                    "repo_slug": render_info["repo_slug"] or "",
                },
                expanded=False,
            )
            if not render_info["deploy_id"]:
                st.caption(t("settings_render_deploy_caption"))
        else:
            st.caption(t("settings_local_runtime_caption"))


def render_bridge_diagnostics_panel():
    """
    渲染 bridge 元信息与诊断内容。
    """
    with st.expander(t("settings_bridge_expander"), expanded=False):
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
            st.caption(t("settings_bridge_empty"))


def render_runtime_history_panel(task_logs, task_runs, task_run_items):
    """
    渲染运行日志与历史概览。
    """
    with st.expander(t("settings_runtime_history"), expanded=False):
        tab_log, tab_hist = st.tabs([t("settings_runtime_log_tab"), t("settings_runtime_history_tab")])
        with tab_log:
            if task_logs:
                st.dataframe(task_logs[-50:], use_container_width=True, hide_index=True)
            else:
                st.caption(t("settings_runtime_no_log"))
        with tab_hist:
            daily_runs, _ = _group_runs_by_day(task_runs, task_run_items)
            if not daily_runs:
                st.caption(t("settings_runtime_no_history"))
            else:
                for day in daily_runs[:5]:
                    st.markdown(t("settings_runtime_day_summary", date=day.get("date"), new_items=day.get("new_items"), success_items=day.get("success_items")))


def render_wish_wall_page(task_logs, task_runs, task_run_items):
    """
    渲染便利签风格的留言板，支持匿名留言和回复。
    """
    st.markdown(t("wish_wall_header"))
    st.caption(t("wish_wall_caption"))
    admin_mode = is_admin_user()

    st.markdown('<div class="wish-wall-shell">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="wish-wall-intro">
            <strong>{html.escape(t("wish_wall_intro_title"))}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("wish_wall_message_form", clear_on_submit=True):
        message = st.text_area(
            t("wish_wall_message_label"),
            height=120,
            placeholder=t("wish_wall_message_placeholder"),
        )
        submitted = st.form_submit_button(t("wish_wall_submit"), type="primary")
        if submitted and message.strip():
            append_guestbook_message(message.strip())
            st.success(t("wish_wall_submit_success"))
            st.rerun()

    guestbook = load_guestbook()
    if not guestbook:
        st.info(t("wish_wall_empty"))
        st.markdown("</div>", unsafe_allow_html=True)
        return

    note_colors = ["wish-note-yellow", "wish-note-pink", "wish-note-blue", "wish-note-green"]
    wall_columns = st.columns(3)
    for idx, msg in enumerate(guestbook):
        col = wall_columns[idx % 3]
        replies = msg.get("replies")
        if not isinstance(replies, list):
            replies = []
        note_class = note_colors[idx % len(note_colors)]
        timestamp_text = str(msg.get("timestamp") or "")[:16].replace("T", " ")
        content_html = html.escape(str(msg.get("content") or "").strip() or t("wish_wall_blank_message")).replace("\n", "<br/>")
        with col:
            st.markdown(
                f"""
                <div class="wish-note {note_class}">
                    <div class="wish-note-head">
                        <span>{html.escape(t("wish_wall_note_prefix"))} #{len(guestbook) - idx}</span>
                        <span>{timestamp_text}</span>
                    </div>
                    <div class="wish-note-body">{content_html}</div>
                    <div class="wish-note-reply-count">{html.escape(t("wish_wall_reply_count", count=len(replies)))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(t("wish_wall_view_reply"), expanded=False):
                if replies:
                    for reply in replies:
                        reply_time = str(reply.get("timestamp") or "")[:16].replace("T", " ")
                        st.markdown(f"**{t('wish_wall_reply_label')}** `{reply_time}`")
                        st.write(str(reply.get("content") or ""))
                else:
                    st.caption(t("wish_wall_no_reply"))

                with st.form(f"wish_reply_form_{msg.get('id')}", clear_on_submit=True):
                    reply_text = st.text_area(
                        t("wish_wall_reply_input"),
                        height=90,
                        placeholder=t("wish_wall_reply_placeholder"),
                        key=f"wish_reply_text_{msg.get('id')}",
                    )
                    reply_submitted = st.form_submit_button(t("wish_wall_reply_submit"))
                    if reply_submitted and reply_text.strip():
                        append_guestbook_reply(str(msg.get("id") or ""), reply_text.strip())
                        st.success(t("wish_wall_reply_success"))
                        st.rerun()

            if admin_mode:
                with st.expander(t("wish_wall_admin_panel"), expanded=False):
                    with st.form(f"wish_admin_form_{msg.get('id')}"):
                        edited_content = st.text_area(
                            t("wish_wall_admin_edit_label"),
                            value=str(msg.get("content") or ""),
                            height=120,
                            key=f"wish_admin_edit_{msg.get('id')}",
                        )
                        save_col, delete_col = st.columns(2)
                        save_clicked = save_col.form_submit_button(t("wish_wall_admin_save"), use_container_width=True)
                        delete_clicked = delete_col.form_submit_button(
                            t("wish_wall_admin_delete"),
                            use_container_width=True,
                            help=t("wish_wall_admin_delete_help"),
                        )
                        if save_clicked:
                            update_guestbook_message(str(msg.get("id") or ""), edited_content)
                            st.success(t("wish_wall_admin_save_success"))
                            st.rerun()
                        if delete_clicked:
                            delete_guestbook_message(str(msg.get("id") or ""))
                            st.success(t("wish_wall_admin_delete_success"))
                            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_settings_diagnostics_page(task_status_value, task_logs, task_runs, task_run_items, *, show_header: bool = True):
    """
    渲染设置与诊断页面，聚合运行状态与 bridge 信息。
    """
    if show_header:
        st.markdown(t("settings_diag_header"))
        st.caption(t("settings_diag_caption"))
        st.caption(t("settings_diag_pipeline", pipeline=pipeline_model_label))

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
        box_title=t("issue_box_title"),
    )

def do_video_summary_single(
    url,
    manual=True,
    fetch_duration=0.0,
    *,
    transcript_text_override: str | None = None,
    summary_state_key: str = "summary_text",
    duration_state_key: str = "summary_duration",
    fact_check_state_prefix: str = "video_fact_check",
    history_source_type: str = "single",
    history_entry_state_key: str = "video_history_entry_id",
):
    """
    基于当前字幕内容生成单视频 AI 总结。
    """
    transcript_value = str(
        transcript_text_override if transcript_text_override is not None else st.session_state.get("transcript_text") or ""
    ).strip()
    if not transcript_value:
        if manual:
            st.warning("请先抓取字幕")
        return

    # --- 限流检查 ---
    client_ip = get_client_ip()
    is_owner = rate_limiter.is_owner(st.session_state.settings)
    if not is_owner:
        allowed, msg = rate_limiter.check_limit(client_ip)
        if not allowed:
            st.warning(msg)
            return

    reset_video_fact_check_state(fact_check_state_prefix)
    print(
        "VideoSummarySingle: "
        f"manual={bool(manual)}, "
        f"url={str(url or '').strip()}, "
        f"fetch_duration={float(fetch_duration):.2f}, "
        f"summary_state_key={summary_state_key}, "
        f"fact_check_state_prefix={fact_check_state_prefix}, "
        f"transcript_len={len(transcript_value)}, "
        "enable_fact_check=False"
    , flush=True)
    t_sum_start = time.time()
    with st.spinner(f"正在请求 AI 总结 ({pipeline_model_label})..."):
        if not manual:
            _update_current_processing_task(
                url=str(url or "").strip(),
                status="running",
                note="字幕已到达，正在生成 AI 总结。",
            )
        summary, err = internal_summarize(
            transcript_value,
            summary_model_selected,
            fact_check_model_selected,
            enable_fact_check=False,
        )

    sum_duration = time.time() - t_sum_start
    total_duration = fetch_duration + sum_duration
    st.session_state[duration_state_key] = {
        "fetch": fetch_duration,
        "summary": sum_duration,
        "total": total_duration,
    }

    if err:
        if not manual:
            _update_current_processing_task(
                url=str(url or "").strip(),
                status="failed",
                error=err,
                note="AI 总结失败。",
            )
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
    st.session_state[summary_state_key] = summary
    if not manual:
        _update_current_processing_task(
            url=str(url or "").strip(),
            status="success",
            result=str(summary or ""),
            note="字幕抓取与总结已完成。",
        )
    start_video_fact_check_async(
        url,
        transcript_value,
        summary,
        summary_state_key=summary_state_key,
        state_prefix=fact_check_state_prefix,
        history_entry_state_key=history_entry_state_key,
    )
    if manual:
        st.success(f"总结完成 | AI生成耗时: {sum_duration:.1f}s")

    try:
        saved_summary = str(st.session_state.get(summary_state_key) or summary or "")
        st.session_state[history_entry_state_key] = add_history_entry(
            history_source_type,
            url,
            saved_summary,
            transcript_value,
        )
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


def detect_video_platform(url: str) -> str:
    """根据链接快速判断视频平台。"""
    text = str(url or "").strip().lower()
    if not text:
        return ""
    if any(part in text for part in ["youtube.com/", "youtu.be/", "youtube.com/watch", "youtube.com/shorts/", "youtube.com/live/"]):
        return "youtube"
    return ""


def choose_video_fetch_strategy(url: str) -> tuple[str, str]:
    """为输入链接选择合适的抓取路径。"""
    platform = detect_video_platform(url)
    if platform == "youtube":
        return "extension", "已选择插件优先链路：由浏览器插件在目标 YouTube 页面提取 transcript，主站不再自动走 Render 服务端抓取。"
    return "extension", "已选择插件提取：当前链接未明确识别平台，先走更通用的插件链路。"


def clear_video_extension_fallback_flags():
    """清理插件失败后回落主站直连的状态位，避免旧状态污染下一轮任务。"""
    st.session_state.video_extension_allow_local_fallback = False
    st.session_state.video_extension_local_fallback_attempted = False


def do_video_fetch_single(url, *, allow_extension_fallback: bool = False) -> bool:
    """
    抓取单视频字幕，并在完成后触发总结。
    """
    url = get_current_video_url(url)
    if not url:
        st.warning("请输入视频链接")
        return False

    # --- 限流检查 ---
    client_ip = get_client_ip()
    is_owner = rate_limiter.is_owner(st.session_state.settings)
    if not is_owner:
        allowed, msg = rate_limiter.check_limit(client_ip)
        if not allowed:
            st.warning(msg)
            return False

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

        status_container.info("正在抓取字幕文本...")
        progress_bar = st.progress(0)
        t_start_all = time.time()

        def update_progress(progress_value, progress_text):
            progress_bar.progress(progress_value, text=progress_text)

        text, err = internal_fetch_transcript(url, update_progress)
        fetch_duration = time.time() - t_start_all

        if err:
            if allow_extension_fallback:
                progress_bar.empty()
                status_container.warning("主站直连失败，正在自动切换插件抓取...")
                handled_by_extension, extension_message = begin_video_extension_request(
                    url,
                    allow_local_fallback=False,
                )
                if handled_by_extension:
                    st.info(extension_message)
                    st.rerun()
                    return False
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
            return False

        _whisper_device_info, text = _extract_whisper_device_info(text)
        st.session_state.whisper_device_tag = ""
        st.session_state.transcript_text = text

        msg = f"🎉 成功获取字幕！ | 耗时: {fetch_duration:.1f}s"
        status_container.success(msg)

        time.sleep(0.5)
        progress_bar.empty()
        do_video_summary_single(url, manual=False, fetch_duration=fetch_duration)
        return True
    except Exception as e:
        if allow_extension_fallback:
            status_container.warning("主站直连异常，正在自动切换插件抓取...")
            handled_by_extension, extension_message = begin_video_extension_request(
                url,
                allow_local_fallback=False,
            )
            if handled_by_extension:
                st.info(extension_message)
                st.rerun()
                return False
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
        return False


def reset_video_extension_request_state(clear_result: bool = True):
    """重置视频插件请求状态，避免旧请求结果污染后续流程。"""
    st.session_state.video_extension_request_pending = False
    st.session_state.video_extension_request_url = ""
    st.session_state.video_extension_request_id = ""
    st.session_state.video_extension_request_component_key = ""
    if clear_result:
        st.session_state.video_extension_request_result = None
        st.session_state.video_extension_request_debug_text = ""


def begin_video_extension_request(url: str, *, allow_local_fallback: bool = False) -> tuple[bool, str]:
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
    st.session_state.video_extension_allow_local_fallback = bool(allow_local_fallback)
    st.session_state.video_extension_local_fallback_attempted = False
    _update_current_processing_task(
        task_id=request_id,
        url=url,
        status="queued",
        title=url,
        note="已发起插件抓取请求，等待扩展响应。",
    )
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
        _update_current_processing_task(
            url=url,
            status="running",
            note="插件已接收请求，正在等待抓取结果回传。",
        )
        return "waiting", "已调用插件抓取，正在等待插件响应...", url

    if not isinstance(normalized_result, dict):
        _update_current_processing_task(
            url=url,
            status="failed",
            error="未检测到可用插件响应，且未再自动回退主站抓取。",
            note="插件响应异常。",
        )
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
        _update_current_processing_task(
            url=url,
            status="failed",
            error=error_text or "unknown_error",
            note="插件未直接返回文本。",
        )
        reset_video_extension_request_state(clear_result=False)
        message = f"插件未直接返回文本（{error_text or 'unknown_error'}）。如果已启用自动续跑，主站会继续使用同一字幕抓取服务获取文本。"
        if tool_version_text:
            message += f" 当前扩展版本：v{tool_version_text}。"
        if helper_text:
            message += f" {helper_text}"
        if debug_summary:
            message += f" 调试：{debug_summary}"
        return "fallback", message, url

    payload_id = str(normalized_result.get("payloadId") or normalized_result.get("payload_id") or "").strip()
    if not payload_id:
        _update_current_processing_task(
            url=url,
            status="failed",
            error="插件未返回 payloadId",
            note="bridge payload 创建失败。",
        )
        reset_video_extension_request_state(clear_result=False)
        return "fallback", "插件未返回 payloadId，且未再自动回退主站抓取。", url

    st.session_state.video_extension_payload_id = payload_id
    st.session_state.video_extension_last_payload_id = ""
    _update_current_processing_task(
        url=url,
        status="running",
        note="插件已返回 payloadId，主站正在读取 bridge payload。",
    )
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


def _render_video_summary_panel(
    *,
    summary_state_key: str = "summary_text",
    duration_state_key: str = "summary_duration",
    fact_check_state_prefix: str = "video_fact_check",
    history_entry_state_key: str = "video_history_entry_id",
) -> None:
    sync_video_fact_check_state(
        summary_state_key=summary_state_key,
        duration_state_key=duration_state_key,
        state_prefix=fact_check_state_prefix,
        history_entry_state_key=history_entry_state_key,
    )
    success_toast_task_id = str(
        st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "success_toast_task_id")) or ""
    ).strip()
    shown_success_toast_task_id = str(
        st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "shown_success_toast_task_id")) or ""
    ).strip()
    if success_toast_task_id and success_toast_task_id != shown_success_toast_task_id:
        st.toast("来源核查已完成，右侧结果已刷新。", icon="✅")
        st.session_state[_fact_check_state_key(fact_check_state_prefix, "shown_success_toast_task_id")] = success_toast_task_id
    with st.container(border=True):
        st.markdown(t("video_summary_title"))
        duration_info = st.session_state.get(duration_state_key) or {}
        if duration_info:
            fetch_t = duration_info.get("fetch", 0)
            sum_t = duration_info.get("summary", 0)
            total_t = duration_info.get("total", 0)
            fact_check_t = duration_info.get("fact_check")
            fact_check_label = "Source check" if get_ui_locale() == "en" else "新闻核查"
            fact_check_part = f" | {fact_check_label}: {float(fact_check_t):.1f}s" if isinstance(fact_check_t, (int, float)) and fact_check_t > 0 else ""
            st.markdown(
                f'<div class="summary-section-meta">{html.escape(t("video_summary_duration", total=total_t, fetch=fetch_t, summary=sum_t, fact_check_part=fact_check_part))}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="summary-section-meta">{html.escape(t("video_summary_pipeline", pipeline=pipeline_model_label))}</div>',
            unsafe_allow_html=True,
        )

        render_summary_content(
            str(st.session_state.get(summary_state_key) or ""),
            fact_title=t("video_fact_check_title"),
        )
    status = str(st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "status")) or "").strip()
    note = str(st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "note")) or "").strip()
    render_browser_title_status(
        status,
        running_title="核查中... - YouTube Summarizer",
        done_title="✅ 核查完成 - YouTube Summarizer",
    )
    if status in {"queued", "running"}:
        st.caption(t("video_fact_check_running"))
        if note:
            st.caption(note)
    elif status == "skipped":
        if note:
            st.caption(f"🕵️ {note}")
    elif status == "error":
        st.warning(
            t(
                "video_fact_check_failed",
                error=str(st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "error")) or "").strip(),
            )
        )
    elif status == "success":
        st.success("✅ 来源核查已完成，右侧结果已刷新。")
        if note:
            st.caption(f"🕵️ {note}")

    return status


def render_video_summary_section(
    *,
    summary_state_key: str = "summary_text",
    duration_state_key: str = "summary_duration",
    fact_check_state_prefix: str = "video_fact_check",
    history_entry_state_key: str = "video_history_entry_id",
) -> None:
    """
    渲染视频链接入口的总结结果与耗时信息。
    """
    summary_value = str(st.session_state.get(summary_state_key) or "").strip()
    if not summary_value:
        return

    initial_status = str(st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "status")) or "").strip()
    run_every = "3s" if initial_status in {"queued", "running"} else None

    @st.fragment(run_every=run_every)
    def _render_video_summary_fragment():
        status = _render_video_summary_panel(
            summary_state_key=summary_state_key,
            duration_state_key=duration_state_key,
            fact_check_state_prefix=fact_check_state_prefix,
            history_entry_state_key=history_entry_state_key,
        )
        st.divider()
        if run_every is not None and status not in {"queued", "running"}:
            st.rerun()

    _render_video_summary_fragment()

    # 当前模式已关闭音频下载/Whisper 转写兜底，不再展示相关脚注。


def render_manual_video_summary_section(
    *,
    summary_state_key: str = "manual_summary_text",
    duration_state_key: str = "manual_summary_duration",
    fact_check_state_prefix: str = "manual_video_fact_check",
    history_entry_state_key: str = "manual_video_history_entry_id",
) -> None:
    """
    渲染插件直达粘贴文本入口的总结结果与耗时信息。
    """
    summary_value = str(st.session_state.get(summary_state_key) or "").strip()
    if not summary_value:
        return

    initial_status = str(st.session_state.get(_fact_check_state_key(fact_check_state_prefix, "status")) or "").strip()
    run_every = "3s" if initial_status in {"queued", "running"} else None

    @st.fragment(run_every=run_every)
    def _render_manual_video_summary_fragment():
        status = _render_video_summary_panel(
            summary_state_key=summary_state_key,
            duration_state_key=duration_state_key,
            fact_check_state_prefix=fact_check_state_prefix,
            history_entry_state_key=history_entry_state_key,
        )
        st.divider()
        if run_every is not None and status not in {"queued", "running"}:
            st.rerun()

    _render_manual_video_summary_fragment()


def render_video_transcript_section():
    """
    渲染视频字幕查看区域。
    """
    if not st.session_state.transcript_text:
        return

    with st.expander(t("transcript_expander"), expanded=False):
        readable_label = t("view_mode_readable")
        raw_label = t("view_mode_raw")
        transcript_view_mode = st.radio(
            t("transcript_view_label"),
            [readable_label, raw_label],
            horizontal=True,
            index=0,
            key="transcript_view_mode",
        )
        if transcript_view_mode == raw_label:
            st.caption(t("transcript_raw_caption"))
            display_text = _raw_transcript_for_display(st.session_state.transcript_text)
        else:
            st.caption(t("transcript_readable_caption"))
            display_text = _clean_transcript_for_display(st.session_state.transcript_text)
        st.text_area(t("transcript_content_label"), display_text, height=360)


def render_video_processing_tab():
    """
    渲染视频处理入口，包括抓取字幕、异步处理、字幕检测和结果展示。
    """
    st.markdown(
        f"""
        <div class="lite-home-hero">
            <h1>{html.escape(t("hero_title"))}</h1>
            <p>{html.escape(t("hero_desc"))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    url = st.text_input(
        t("video_input_label"),
        key="input_url",
        placeholder=t("video_input_placeholder"),
        label_visibility="collapsed",
    )
    st.markdown(
        f'<div class="lite-search-meta">{html.escape(t("video_input_meta"))}</div>',
        unsafe_allow_html=True,
    )
    path_col1, path_col2 = st.columns(2, gap="large")
    with path_col1:
        with st.container(border=True):
            st.markdown(
                f"""
                <div class="lite-entry-card">
                    <div class="lite-entry-card-title">{html.escape(t("home_path_input_title"))}</div>
                    <p class="lite-entry-card-desc">{html.escape(t("home_path_input_desc"))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with path_col2:
        with st.container(border=True):
            st.markdown(
                f"""
                <div class="lite-entry-card">
                    <div class="lite-entry-card-title">{html.escape(t("home_path_plugin_title"))}</div>
                    <p class="lite-entry-card-desc">{html.escape(t("home_path_plugin_desc"))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    remember_current_video_url(url)
    resolved_url = get_current_video_url(url)
    fetch_strategy, fetch_strategy_message = choose_video_fetch_strategy(resolved_url)
    auto_fetch_pending = bool(st.session_state.get("video_auto_fetch_pending"))
    auto_fetch_url = get_current_video_url(st.session_state.get("video_auto_fetch_url") or resolved_url)
    auto_fetch_route = str(st.session_state.get("video_auto_fetch_route") or "").strip()
    if auto_fetch_pending and auto_fetch_url:
        st.session_state.video_auto_fetch_pending = False
        if auto_fetch_route in {"server_direct", "local_direct"} and admin_mode:
            st.info(t("video_auto_direct"))
            fetch_succeeded = do_video_fetch_single(auto_fetch_url, allow_extension_fallback=False)
            if fetch_succeeded:
                render_video_summary_section()
                render_video_transcript_section()
            return
        handled_by_extension, extension_message = begin_video_extension_request(
            auto_fetch_url,
            allow_local_fallback=False,
        )
        if handled_by_extension:
            st.info(t("video_auto_extension"))
            st.info(extension_message)
            st.rerun()
            return
    extension_status, extension_message, extension_url = try_video_extension_first()
    if extension_status == "waiting" and extension_message:
        st.info(extension_message)
    elif extension_status == "payload_ready":
        clear_video_extension_fallback_flags()
        st.rerun()
    elif extension_status == "fallback":
        should_auto_local_fallback = (
            bool(st.session_state.get("video_extension_allow_local_fallback"))
            and not bool(st.session_state.get("video_extension_local_fallback_attempted"))
            and bool(extension_url)
        )
        if should_auto_local_fallback:
            st.session_state.video_extension_local_fallback_attempted = True
            clear_video_extension_fallback_flags()
            st.error("插件未直接返回文本；已停止自动回退 Render 服务端抓取，避免触发 YouTube 429 限流。请在目标 YouTube 视频页直接点击插件重试。")
            return
        clear_video_extension_fallback_flags()
        if extension_message:
            st.error(extension_message)
        debug_text = str(st.session_state.get("video_extension_request_debug_text") or "").strip()
        if debug_text:
            with st.expander(t("video_extension_debug"), expanded=False):
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

    if resolved_url:
        strategy_label = {
            "server_direct": "统一服务端字幕抓取",
            "local_direct": "统一服务端字幕抓取",
            "extension": "统一插件页面提取",
        }.get(fetch_strategy, "插件提取")
        st.caption(f"当前智能路径：`{strategy_label}`。{fetch_strategy_message}")

    action_spacer_left, action_main, action_spacer_right = st.columns([1.35, 1.3, 1.35])
    with action_main:
        fetch_btn = st.button("🚀 智能抓取并总结", type="primary", use_container_width=True, key="btn_single_fetch")

    sub_spacer_left, sub_col1, sub_col2, sub_spacer_right = st.columns([1.2, 1, 1, 1.2])
    with sub_col1:
        summary_btn = st.button("🤖 仅重新生成总结", use_container_width=True, key="btn_single_sum")
    with sub_col2:
        check_btn = st.button("🔍 检测可用字幕", use_container_width=True, key="btn_single_check")
    st.markdown(
        '<div class="lite-home-helper">也可以直接在视频页点击插件，一键获取总结。</div>',
        unsafe_allow_html=True,
    )

    if fetch_btn:
        if not resolved_url:
            st.warning("请输入视频链接")
            return
        if fetch_strategy == "server_direct" and admin_mode:
            st.info(fetch_strategy_message)
            fetch_succeeded = do_video_fetch_single(resolved_url, allow_extension_fallback=True)
            if fetch_succeeded:
                render_video_summary_section()
                render_video_transcript_section()
            return
        handled_by_extension, extension_message = begin_video_extension_request(
            resolved_url,
            allow_local_fallback=False,
        )
        if handled_by_extension:
            st.info(fetch_strategy_message)
            st.info(extension_message)
            st.rerun()
        st.error("未能发起插件请求，请确认扩展已在当前页面注入后重试。")
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


def _should_use_video_pipeline_for_extension_summary(manual_source_url: str, manual_transcript: str) -> bool:
    if not str(manual_transcript or "").strip():
        return False
    if not _is_supported_video_source_url(manual_source_url):
        return False
    # 只要文本绑定的是受支持的视频链接，就统一走视频总结/新闻核查链路，
    # 避免“输入链接”和“插件导入/手动粘贴”在同一条新闻上走出两套不同结果。
    return True


def run_manual_transcript_summary(manual_source_url, manual_transcript, auto_paste_sum):
    """
    对手动粘贴或 bridge 自动注入的字幕文本执行总结。
    """
    if not manual_transcript.strip():
        st.warning("请先粘贴字幕文本。")
        return

    # --- 限流检查 ---
    client_ip = get_client_ip()
    is_owner = rate_limiter.is_owner(st.session_state.settings)
    if not is_owner:
        allowed, msg = rate_limiter.check_limit(client_ip)
        if not allowed:
            st.warning(msg)
            return

    current_payload_id = st.session_state.manual_auto_payload_id if auto_paste_sum else ""
    if _should_use_video_pipeline_for_extension_summary(manual_source_url, manual_transcript):
        manual_meta = st.session_state.manual_bridge_meta or {}
        history_source_type = "manual_transcript"
        if manual_meta.get("source_kind") == "extension":
            history_source_type = "extension_bridge"
        elif manual_meta.get("source_kind") == "local_tool":
            history_source_type = "local_tool_bridge"
        st.session_state.manual_summary_text = ""
        st.session_state.manual_summary_duration = {}
        st.session_state.current_video_url = str(manual_source_url or "").strip()
        reset_video_fact_check_state("manual_video_fact_check")
        if current_payload_id:
            st.session_state.manual_last_payload_id = current_payload_id
            st.session_state.manual_auto_payload_id = ""
            try:
                st.query_params.clear()
            except Exception:
                pass
        do_video_summary_single(
            str(manual_source_url or "").strip(),
            manual=False,
            fetch_duration=0.0,
            transcript_text_override=manual_transcript.strip(),
            summary_state_key="manual_summary_text",
            duration_state_key="manual_summary_duration",
            fact_check_state_prefix="manual_video_fact_check",
            history_source_type=history_source_type,
            history_entry_state_key="manual_video_history_entry_id",
        )
        return

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
    manual_source_url = str(st.session_state.get("manual_source_url") or "").strip()
    if _should_use_video_pipeline_for_extension_summary(manual_source_url, st.session_state.get("manual_transcript_text") or ""):
        if not st.session_state.manual_summary_text:
            return
        render_manual_video_summary_section(
            summary_state_key="manual_summary_text",
            duration_state_key="manual_summary_duration",
            fact_check_state_prefix="manual_video_fact_check",
        )
        with st.expander(t("manual_transcript_expander"), expanded=False):
            st.text_area(t("manual_transcript_label"), st.session_state.manual_transcript_text, height=320, key="manual_transcript_view")
        return

    if not st.session_state.manual_summary_text:
        return

    st.markdown(t("manual_summary_title"))
    manual_dur = float((st.session_state.manual_summary_duration or {}).get("summary") or 0.0)
    if manual_dur:
        st.caption(t("manual_summary_duration", duration=manual_dur))
    st.caption(t("video_summary_pipeline", pipeline=pipeline_model_label))

    if st.session_state.manual_bridge_meta:
        bridge_context = build_manual_bridge_context(st.session_state.manual_bridge_meta)
        if bridge_context.get("summary"):
            st.info(t("manual_summary_source", summary=bridge_context["summary"]))
        if bridge_context.get("details"):
            st.caption(bridge_context["details"])
        bridge_meta_text = format_manual_bridge_meta(st.session_state.manual_bridge_meta)
        if bridge_meta_text:
            with st.expander(t("manual_bridge_meta_expander"), expanded=False):
                st.caption(bridge_meta_text)

    render_manual_video_summary_section(
        summary_state_key="manual_summary_text",
        duration_state_key="manual_summary_duration",
        fact_check_state_prefix="manual_video_fact_check",
    )
    with st.expander(t("manual_transcript_expander"), expanded=False):
        st.text_area(t("manual_transcript_label"), st.session_state.manual_transcript_text, height=320, key="manual_transcript_view")


def render_text_processing_tab():
    """
    渲染粘贴文本入口，兼容扩展 bridge 自动回填与手动粘贴总结。
    """
    st.info(t("manual_info"))
    render_manual_bridge_status()

    manual_source_url = st.text_input(
        t("manual_source_label"),
        key="manual_source_url",
        placeholder=t("manual_source_placeholder"),
    )
    manual_transcript = st.text_area(
        t("manual_input_label"),
        height=260,
        key="manual_transcript_text",
        placeholder=t("manual_input_placeholder"),
    )
    paste_col1, paste_col2 = st.columns([1, 3])
    with paste_col1:
        paste_sum_btn = st.button(t("manual_summary_btn"), type="primary", use_container_width=True, key="btn_manual_sum")
    with paste_col2:
        st.caption(t("manual_fallback_caption"))

    auto_paste_sum = bool(
        st.session_state.manual_auto_payload_id
        and st.session_state.manual_auto_payload_id != st.session_state.manual_last_payload_id
        and manual_transcript.strip()
    )
    if auto_paste_sum:
        st.caption(t("manual_auto_start"))

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

    st.markdown(t("document_summary_title"))
    file_name = doc_meta.get("file_name", "未命名文档")
    file_type = str(doc_meta.get("file_type") or "").upper() or "DOC"
    char_count = int(doc_meta.get("char_count") or 0)
    page_count = doc_meta.get("page_count")
    chunk_count = int(doc_meta.get("chunk_count") or 1)
    strategy = t("document_strategy_chunked") if doc_meta.get("strategy") == "chunked" else t("document_strategy_direct")
    duration = float(doc_meta.get("duration") or 0.0)
    source_url = str(doc_meta.get("source_url") or source_url_state or "").strip()
    ocr_used = bool(doc_meta.get("ocr_used", False))
    fact_check_plan = doc_meta.get("fact_check_plan") or {}
    doc_type = str(fact_check_plan.get("document_type") or "unknown")
    should_fact_check = bool(fact_check_plan.get("should_fact_check", False))
    fact_check_reason = str(fact_check_plan.get("reason") or "").strip()
    recommended_claim_count = int(fact_check_plan.get("recommended_claim_count") or 0)

    meta_parts = [
        f"{t('document_meta_file')}: `{file_name}`",
        f"{t('document_meta_type')}: `{file_type}`",
        f"{t('document_meta_body')}: `{t('document_meta_chars', count=char_count)}`",
        f"{t('document_meta_strategy')}: `{strategy}`",
        f"{t('document_meta_chunks')}: `{chunk_count}`",
    ]
    if page_count:
        meta_parts.append(f"{t('document_meta_pages')}: `{page_count}`")
    if duration:
        meta_parts.append(f"{t('document_meta_duration')}: `{duration:.1f}s`")
    if ocr_used:
        meta_parts.append(t("document_meta_ocr"))
    meta_parts.append(f"{t('document_meta_doc_type')}: `{doc_type}`")
    st.caption(" | ".join(meta_parts))
    if source_url:
        st.caption(t("document_source_link", url=source_url))
    if fact_check_reason:
        st.caption(
            t(
                "document_fact_check_status",
                status=t("document_fact_check_enabled") if should_fact_check else t("document_fact_check_skipped"),
                reason=fact_check_reason,
            )
        )

    if fact_check_content:
        render_summary_fact_check(
            summary_text,
            fact_check_content,
            fact_title=t("document_fact_check_title"),
            fact_tab_label=t("document_fact_check_tab_title"),
        )
    else:
        st.markdown(summary_text)
        if should_fact_check and recommended_claim_count > 0:
            st.warning(t("document_fact_check_warning", count=recommended_claim_count))
        else:
            st.info(t("document_fact_check_info"))

    with st.expander(t("document_expander"), expanded=False):
        readable_label = t("view_mode_readable")
        raw_label = t("view_mode_raw")
        doc_view_mode = st.radio(
            t("document_view_label"),
            [readable_label, raw_label],
            horizontal=True,
            index=0,
            key=f"document_view_mode_{source_key}",
        )
        if doc_view_mode == raw_label:
            st.caption(t("document_raw_caption"))
            display_text = raw_text
        else:
            st.caption(t("document_readable_caption"))
            display_text = clean_text
        st.text_area(t("document_content_label"), display_text, height=420, key=f"document_content_{source_key}")


def run_uploaded_document_summary(uploaded_doc):
    """
    执行本地上传文档的提取与总结。
    """
    if not uploaded_doc:
        st.warning(t("document_upload_missing"))
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
    st.info(t("document_info"))
    st.caption(t("document_info_caption"))

    doc_source_upload, doc_source_url_tab = st.tabs([t("document_tab_upload"), t("document_tab_url")])

    with doc_source_upload:
        st.caption(t("document_upload_caption"))
        uploaded_doc = st.file_uploader(
            t("document_upload_label"),
            type=["pdf", "docx", "txt", "md", "markdown", "pptx"],
            key="doc_uploader",
            label_visibility="collapsed",
        )
        doc_col1, doc_col2 = st.columns([1, 2])
        with doc_col1:
            doc_sum_btn = st.button(t("document_summary_btn"), type="primary", use_container_width=True, key="btn_doc_sum")
        with doc_col2:
            st.caption(t("document_upload_footer"))

        if doc_sum_btn:
            run_uploaded_document_summary(uploaded_doc)
        render_document_result("upload")

    with doc_source_url_tab:
        doc_url = st.text_input(
            t("document_url_label"),
            key="document_url_input",
            placeholder=t("document_url_placeholder"),
        )
        doc_url_col1, doc_url_col2 = st.columns([1, 2])
        with doc_url_col1:
            doc_url_btn = st.button(t("document_url_btn"), type="primary", use_container_width=True, key="btn_doc_url_sum")
        with doc_url_col2:
            st.caption(t("document_url_footer"))

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
        st.warning(t("subscription_input_required"))
        return

    is_url = (
        "http" in new_channel_input
        or "://" in new_channel_input
        or new_channel_input.startswith("@")
        or "www." in new_channel_input
    )

    if is_url:
        with st.spinner(t("subscription_fetch_channel")):
            try:
                eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                cid, cname, curl, cavatar, cplatform = get_channel_info(
                    new_channel_input,
                    proxy_url=eff_proxy,
                    timeout_seconds=float(timeout),
                )
                if _append_subscription(cid, cname, curl, cavatar, cplatform):
                    st.success(t("subscription_added_success", name=cname, platform=cplatform))
                    st.rerun()
                st.warning(t("subscription_exists", name=cname))
            except Exception as e:
                st.error(t("subscription_add_failed", error=e))
        return

    st.session_state.search_results = None
    with st.spinner(t("subscription_searching", keyword=new_channel_input)):
        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
        results = search_channels(
            new_channel_input,
            limit=3,
            proxy_url=eff_proxy,
            timeout_seconds=float(timeout),
        )
        st.session_state.search_results = results
        if not results.get("youtube"):
            st.warning(t("subscription_not_found"))
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
            else:
                st.markdown(
                    "<div style='height: 60px; display: flex; align-items: center; justify-content: center; font-size: 30px; background-color: #f0f0f0; border-radius: 50%;'>📺</div>",
                    unsafe_allow_html=True,
                )
        with c_info:
            name = item.get("name", t("subscription_unknown_name"))
            desc = item.get("desc", "")
            url = item.get("url", "")
            st.markdown(f"**[{name}]({url})**")
            if desc:
                st.caption(desc)
            else:
                st.caption(t("subscription_youtube_channel"))
        with c_btn:
            st.write("")
            if st.button(t("subscription_search_add"), key=f"add_res_{item['platform']}_{item['id']}", use_container_width=True):
                with st.spinner(t("subscription_fetch_channel")):
                    try:
                        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
                        cid, cname, curl, cavatar, cplatform = get_channel_info(
                            item["url"],
                            proxy_url=eff_proxy,
                            timeout_seconds=float(timeout),
                        )
                        if _append_subscription(cid, cname, curl, cavatar, cplatform):
                            st.session_state.search_results = None
                            st.success(t("subscription_added_short", name=cname))
                            st.rerun()
                        st.warning(t("subscription_exists_short", name=cname))
                    except Exception as e:
                        st.error(t("subscription_add_failed", error=e))


def render_subscription_search_results():
    """
    渲染频道搜索结果列表。
    """
    if not st.session_state.get("search_results"):
        return

    st.divider()
    st.markdown(t("subscription_search_results"))

    res_yt = st.session_state.search_results.get("youtube", [])
    
    if not res_yt:
        st.info(t("subscription_no_results"))
    else:
        for item in res_yt:
            render_subscription_search_item(item)

    if st.button(t("subscription_close_search"), key="close_search"):
        st.session_state.search_results = None
        st.rerun()


def split_subscriptions_by_platform():
    """
    获取 YouTube 订阅。
    """
    return st.session_state.subscriptions, []


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
            if st.button("🗑️", key=f"del_{real_index}_{index_key_suffix}", help=t("subscription_delete_help", name=sub["name"]), use_container_width=True):
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
        if st.button("🗑️", key=f"del_list_{real_index}_{index_key_suffix}", help=t("subscription_delete_help", name=sub["name"])):
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
    if view_mode == "grid":
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
    st.markdown(t("subscription_list_title"))
    view_mode_options = {
        t("subscription_view_list"): "list",
        t("subscription_view_grid"): "grid",
    }
    view_mode_label = st.radio(
        t("subscription_view_mode"),
        list(view_mode_options.keys()),
        horizontal=True,
        index=0,
        key="sub_view_mode",
        label_visibility="collapsed",
    )
    view_mode = view_mode_options.get(view_mode_label, "list")

    if not st.session_state.subscriptions:
        st.info(t("subscription_empty"))
        return

    yt_subs, _ = split_subscriptions_by_platform()
    render_subscription_platform_section(t("subscription_channel_section"), yt_subs, "yt", view_mode)


def render_subscription_management_panel():
    """
    渲染订阅管理面板，包含添加、搜索结果和订阅列表。
    """
    with st.expander(t("subscription_manage_expander"), expanded=False):
        st.markdown(t("subscription_add_new"))
        new_channel_input = st.text_input(
            t("subscription_input_label"),
            key="sub_input",
            placeholder=t("subscription_input_placeholder"),
        )

        col_act_1, col_act_2 = st.columns([1, 3])
        with col_act_1:
            if st.button(t("subscription_search_button"), use_container_width=True):
                handle_subscription_search_or_add(new_channel_input)

        render_subscription_search_results()
        render_subscription_list_panel()


def _resolve_subscription_platform_display(sub):
    """
    返回 YouTube 平台标识。
    """
    return "📺 YouTube", "red"


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
        st.info(t("subscription_empty_update"))
        st.session_state.is_updating_all = False
        return

    st.session_state.is_updating_all = True
    st.session_state.updates = {}

    with st.status(t("subscription_checking_status"), expanded=True) as status:
        progress_text = t("subscription_check_prepare_proxy")
        progress_bar = st.progress(0, text=progress_text)

        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
        progress_bar.progress(0, text=t("subscription_check_prepare_tasks"))

        from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(len(st.session_state.subscriptions), 20)
    progress_bar.progress(0, text=t("subscription_check_launch", count=max_workers))
    start_time = time.time()
    status.update(label=t("subscription_check_running", elapsed=0), state="running")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sub = {
            executor.submit(_check_subscription_recent_videos, sub, eff_proxy, timeout): sub
            for sub in st.session_state.subscriptions
        }

        completed_count = 0
        total_subs = len(st.session_state.subscriptions)
        progress_bar.progress(0.01, text=t("subscription_check_waiting", done=0, total=total_subs))

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
                text=t(
                    "subscription_check_progress",
                    done=completed_count,
                    total=total_subs,
                    name=sub["name"],
                    remain=int(remain_time),
                ),
            )
            status.update(label=t("subscription_check_running", elapsed=int(elapsed)), state="running")

            try:
                sid, result = future.result()
                if isinstance(result, list):
                    if result:
                        st.session_state.updates[sid] = result
                        status.write(t("subscription_check_found", name=sub["name"], count=len(result)))
                else:
                    status.write(t("subscription_check_failed", name=sub["name"], error=result))
            except Exception as exc:
                status.write(t("subscription_check_exception", name=sub["name"], error=exc))

    total_elapsed = time.time() - start_time
    progress_bar.progress(1.0, text=t("subscription_check_done_progress", elapsed=int(total_elapsed)))
    time.sleep(0.5)
    progress_bar.empty()
    status.update(label=t("subscription_check_done", elapsed=int(total_elapsed)), state="complete", expanded=False)
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
        fact_title=t("video_fact_check_title"),
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
    footer_str = t(
        "subscription_summary_footer",
        pipeline=pipeline_model_label,
        device=whisper_device_info,
        duration=duration,
    )

    try:
        raw_text = transcript_text or ""
        if "<!-- TIMING:" in raw_text:
            import re

            m_timing = re.search(r"<!-- TIMING: download=([\d\.]+), transcribe=([\d\.]+) -->", raw_text)
            if m_timing:
                dl_time = float(m_timing.group(1))
                tr_time = float(m_timing.group(2))
                footer_str += t(
                    "subscription_summary_footer_timing",
                    download=dl_time,
                    transcribe=tr_time,
                    duration=duration,
                )
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
        return _call_with_optional_kwargs(
            summarize_text,
            text,
            api_key,
            base_url,
            summary_model_selected,
            proxy_input,
            fact_check_model=fact_check_model_selected,
            ui_locale=get_ui_locale(),
            stream=False,
        )

    return _call_with_optional_kwargs(
        summarize_text,
        text,
        api_key,
        base_url,
        summary_model_selected,
        proxy_input,
        fact_check_model=fact_check_model_selected,
        ui_locale=get_ui_locale(),
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
            st.markdown(t("video_summary_title"))
        with c_head_2:
            if st.button("✕", key=f"close_{video['id']}", help=t("subscription_summary_close")):
                st.session_state.viewing_summaries.pop(video["id"])
                st.rerun()

        cache_key = f"cache_sum_{video['id']}"
        if render_cached_subscription_summary(video["id"]):
            return

        status_container = st.empty()
        progress_container = st.empty()
        progress_bar = progress_container.progress(0, text=t("subscription_summary_init"))
        start_time = time.time()
        progress_bar.progress(10, text=t("subscription_summary_prepare"))

        try:
            text, err, whisper_device_info = fetch_subscription_video_transcript(video["url"], progress_bar)
            if err:
                progress_container.empty()
                status_container.error(t("subscription_summary_transcript_failed", error=err))
                return

            progress_bar.progress(40, text=t("subscription_summary_ai_ready"))
            if summary_model_selected != fact_check_model_selected:
                status_container.info(t("subscription_summary_ai_dual"))
            else:
                status_container.info(t("subscription_summary_ai_stream"))

            if not api_key:
                progress_container.empty()
                status_container.error(t("subscription_summary_need_api"))
                return

            try:
                progress_bar.progress(50, text=t("subscription_summary_connect_api"))
                stream = create_subscription_summary_stream(text)

                progress_bar.progress(60, text=t("subscription_summary_receive"))
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
                status_container.error(t("subscription_summary_error", error=e))
        except Exception as outer_e:
            progress_container.empty()
            status_container.error(t("subscription_process_error", error=outer_e))


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
            duration_text = t(
                "subscription_duration_hm",
                hours=int(duration // 3600),
                minutes=int((duration % 3600) // 60),
            )
        else:
            duration_text = t(
                "subscription_duration_ms",
                minutes=int(duration // 60),
                seconds=int(duration % 60),
            )
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

            if st.button(t("subscription_summarize_btn"), key=f"btn_sum_{video['id']}", use_container_width=True):
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
        st.info(t("subscription_updates_none_after", time=st.session_state.last_update_check))
    else:
        st.info(t("subscription_updates_none_before"))


def render_subscription_updates_panel():
    """
    渲染订阅更新检查与最新动态列表。
    """
    with st.container():
        st.subheader(t("subscription_updates_header"))

        if st.button(t("subscription_updates_check_all"), type="primary", use_container_width=True):
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
        selected_date = st.selectbox(t("daily_report_select_date"), dates, index=default_index, label_visibility="collapsed")
    with filter_c2:
        status_options = {
            t("filter_all"): "all",
            t("daily_report_filter_success"): "success",
            t("daily_report_filter_failed"): "failed",
        }
        status_label = st.selectbox(
            t("daily_report_filter_status"),
            list(status_options.keys()),
            index=0,
            label_visibility="collapsed",
        )
        status_filter = status_options.get(status_label, "all")
    with filter_c3:
        keyword = st.text_input(
            t("daily_report_search_title"),
            value="",
            placeholder=t("daily_report_search_placeholder"),
            label_visibility="collapsed",
        )

    return selected_date, status_filter, keyword


def render_daily_report_metrics(day_info):
    """
    渲染选中日期的日报统计信息。
    """
    if not day_info:
        return

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric(t("daily_report_metric_total"), day_info.get("total_items"))
    metric_2.metric(t("status_success"), day_info.get("success_items"))
    metric_3.metric(t("status_failed"), day_info.get("failed_items"))


def filter_daily_report_items(items, status_filter, keyword):
    """
    根据状态与关键词过滤日报条目。
    """
    filtered_items = []
    items_sorted = sorted(items, key=lambda item: item.get("created_at") or "", reverse=True)
    keyword_text = keyword.strip().lower() if keyword else ""

    for item in items_sorted:
        status = item.get("status") or ""
        if status_filter == "success" and status != "success":
            continue
        if status_filter == "failed" and status == "success":
            continue

        title = item.get("title") or t("daily_report_item_untitled")
        if keyword_text and keyword_text not in title.lower():
            continue
        filtered_items.append(item)

    return filtered_items


def render_daily_report_item(item):
    """
    渲染单条日报记录卡片。
    """
    status = item.get("status") or ""
    title = item.get("title") or t("daily_report_item_untitled")

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
                st.success(t("status_success"), icon="✅")
            else:
                st.error(t("status_failed"), icon="❌")

        if item.get("url"):
            st.caption(f"🔗 [{t('daily_report_video_link')}]({item.get('url')})")

        if status == "success":
            with st.expander(t("daily_report_view_summary"), expanded=False):
                render_summary_content(
                    item.get("summary") or "",
                    fact_title=t("video_fact_check_title"),
                )
        else:
            err_text = item.get("error") or t("status_unknown")
            st.error(t("task_failure_reason", error=err_text))


def render_daily_report_tab(run_items):
    """
    渲染每日简报子页。
    """
    daily_items, items_by_day = _group_items_by_day(run_items)
    if not daily_items:
        st.info(t("daily_report_empty"))
        return

    selected_date, status_filter, keyword = render_daily_report_filters(daily_items)
    day_info = next((item for item in daily_items if item.get("date") == selected_date), None)
    render_daily_report_metrics(day_info)

    st.divider()
    items = items_by_day.get(selected_date, [])
    if not items:
        st.caption(t("daily_report_empty_date"))
        return

    filtered_items = filter_daily_report_items(items, status_filter, keyword)
    if not filtered_items:
        st.caption(t("daily_report_empty_filter"))
        return

    for item in filtered_items:
        render_daily_report_item(item)


def render_task_quick_actions(settings, tasks, runs, run_items, processed_ids):
    """
    渲染任务管理中的快捷操作区域。
    """
    st.markdown(t("automation_quick_actions"))
    if not tasks:
        st.caption(t("automation_no_tasks"))
        return

    if st.button(t("automation_run_all"), type="primary", use_container_width=True):
        with st.spinner(t("automation_running_all")):
            for task in tasks:
                if not task.get("enabled"):
                    continue
                settings = _run_task_once(task, settings)

            runs = settings.get("scheduled_runs") or runs
            run_items = settings.get("scheduled_run_items") or run_items
            processed_ids = settings.get("scheduled_processed_ids") or processed_ids
            _save_scheduled_state(settings, tasks, settings.get("schedule_logs") or [], runs, run_items, processed_ids)

        st.toast(t("automation_run_all_done"), icon="✅")
        st.rerun()


def build_task_subscription_label_map(subs):
    """
    为任务创建弹层构建频道标签到订阅对象的映射。
    """
    label_map = {}
    for sub in subs:
        label = f"{sub.get('name')} (youtube)"
        label_map[label] = sub
    return label_map


def render_task_schedule_inputs():
    """
    渲染任务调度配置输入，并返回统一的配置结果。
    """
    st.divider()
    st.caption(t("automation_schedule_title"))
    simple_mode = st.toggle(t("automation_simple_mode"), value=True)
    schedule_options = {
        t("automation_schedule_daily"): "daily",
        t("automation_schedule_weekly"): "weekly",
        t("automation_schedule_interval"): "interval",
        t("automation_schedule_cron"): "cron",
    }
    weekday_labels = _automation_weekday_labels()

    interval_hours = 0
    cron_value = ""
    weekdays_value = []
    schedule_time = None

    if simple_mode:
        schedule_type = "daily"
        schedule_time = st.time_input(t("automation_schedule_daily_time"), value=dt_time(9, 0))
    else:
        schedule_type_label = st.selectbox(t("automation_schedule_type"), list(schedule_options.keys()))
        schedule_type = schedule_options.get(schedule_type_label, "daily")
        if schedule_type == "daily":
            schedule_time = st.time_input(t("automation_schedule_time_point"), value=dt_time(9, 0))
        elif schedule_type == "weekly":
            schedule_time = st.time_input(t("automation_schedule_time_point"), value=dt_time(9, 0))
            selected_days = st.multiselect(
                t("automation_schedule_weekdays"),
                weekday_labels,
                default=weekday_labels[:5],
            )
            weekdays_value = [weekday_labels.index(day) for day in selected_days]
        elif schedule_type == "interval":
            interval_hours = st.number_input(t("automation_schedule_interval_hours"), 1, 168, 6)
        else:
            cron_value = st.text_input(t("automation_schedule_cron_expr"), "0 9 * * *")

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
    normalized = str(schedule_type_label or "").strip().lower()
    if normalized in ["daily", "每天"]:
        return "daily"
    if normalized in ["weekly", "每周"]:
        return "weekly"
    if normalized in ["interval", "间隔小时"]:
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
    st.markdown(t("automation_create_task_title"))
    with st.popover(t("automation_create_task_btn"), use_container_width=True):
        if not st.session_state.subscriptions:
            st.warning(t("automation_create_task_need_sub"))
            return

        subs = st.session_state.subscriptions
        label_map = build_task_subscription_label_map(subs)

        keyword = st.text_input(
            t("automation_search_channel"),
            placeholder=t("automation_search_channel_placeholder"),
            label_visibility="collapsed",
        )
        filtered_labels = [label for label in label_map.keys() if keyword.lower() in label.lower()] if keyword else list(label_map.keys())

        if st.button(t("automation_select_all"), use_container_width=True):
            st.session_state.selected_channel_labels = filtered_labels
            st.rerun()

        if "selected_channel_labels" not in st.session_state:
            st.session_state.selected_channel_labels = []

        selected_labels = st.multiselect(t("automation_select_channels"), filtered_labels, default=st.session_state.selected_channel_labels)
        st.session_state.selected_channel_labels = selected_labels

        schedule_config = render_task_schedule_inputs()

        if st.button(t("automation_create_task_submit"), type="primary", use_container_width=True):
            if not selected_labels:
                st.error(t("automation_create_task_pick_channel"))
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
                st.success(t("automation_create_task_success", count=added_count))
                st.rerun()
            st.warning(t("automation_create_task_skip_exists"))


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
            st.caption(t("automation_task_next_run", time=next_run.strftime("%m-%d %H:%M") if next_run else "-"))
            if task.get("last_error"):
                st.caption(f":red[{task.get('last_error')[:10]}...]")
        with c3:
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button(t("automation_task_toggle_disable") if is_enabled else t("automation_task_toggle_enable"), key=f"tg_{task['id']}"):
                    task["enabled"] = not task["enabled"]
                    _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                    st.rerun()
            with col_btn2:
                if st.button("🗑️", key=f"del_{task['id']}", help=t("automation_task_delete_help")):
                    tasks[:] = [item for item in tasks if item["id"] != task["id"]]
                    _save_scheduled_state(settings, tasks, logs, runs, run_items, processed_ids)
                    st.rerun()


def render_task_list_panel(settings, tasks, logs, runs, run_items, processed_ids):
    """
    渲染任务列表区域。
    """
    st.divider()
    st.markdown(t("automation_task_list_title"))
    if not tasks:
        st.info(t("automation_task_list_empty"))
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

    sub_tab_report, sub_tab_manage = st.tabs([t("automation_daily_tab"), t("automation_manage_tab")])

    with sub_tab_report:
        render_daily_report_tab(run_items)

    with sub_tab_manage:
        render_task_management_tab(settings, tasks, logs, runs, run_items, processed_ids)


def render_processing_center_page(current_bg_task_id, current_bg_task_status):
    """
    渲染 Lite 首页，突出视频链接与插件直达总结。
    """
    render_quota_status()
    render_video_processing_tab()

    with st.expander("更多输入方式", expanded=bool(st.session_state.prefer_paste_tab)):
        extra_tab_paste, extra_tab_doc = st.tabs(["✍️ 粘贴文本", "📄 上传文档"])
        with extra_tab_paste:
            render_text_processing_tab()
        with extra_tab_doc:
            render_document_processing_tab()


def render_automation_page(*, show_header: bool = True):
    """
    渲染订阅自动化页面壳，统一组织订阅动态与规则日报。
    """
    if show_header:
        st.markdown(t("automation_header"))
        st.caption(t("automation_caption"))
    automation_tab_subs, automation_tab_rules = st.tabs([t("automation_tab_subs"), t("automation_tab_rules")])

    with automation_tab_subs:
        render_subscription_dynamic_tab()

    with automation_tab_rules:
        render_automation_rules_tab()


def render_lite_settings_page(current_bg_task_id, current_bg_task_status, task_status_value, task_logs, task_runs, task_run_items):
    """
    渲染 Lite 版设置页：优先保留普通用户真正需要的设置。
    """
    st.markdown(t("lite_settings_header"))
    st.caption(t("lite_settings_caption"))

    st.markdown(
        f"""
        <div class="lite-settings-card">
            <strong>{html.escape(t("lite_settings_recommend_title"))}</strong><br/>
            {html.escape(t("lite_settings_recommend_body"))}
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(t("lite_settings_advanced"), expanded=False):
        st.caption(t("lite_settings_advanced_caption", pipeline=pipeline_model_label))
        with st.form("lite_model_settings_form"):
            api_key_value = st.text_input(
                "API Key",
                value=str(st.session_state.settings.get("api_key") or ""),
                type="password",
                help=t("lite_settings_api_key_help"),
            )
            base_url_value = st.text_input(
                "Base URL",
                value=str(st.session_state.settings.get("base_url") or "https://api.openai.com/v1"),
            )
            summary_model_value = st.text_input(
                t("lite_settings_summary_model"),
                value=str(st.session_state.settings.get("summary_model") or DEFAULT_SUMMARY_MODEL),
                help=t("lite_settings_summary_model_help"),
            )
            fact_check_model_value = st.text_input(
                t("lite_settings_fact_model"),
                value=str(st.session_state.settings.get("fact_check_model") or DEFAULT_FACT_CHECK_MODEL),
                help=t("lite_settings_fact_model_help"),
            )
            use_deepseek_defaults = st.form_submit_button(t("lite_settings_use_defaults"))
            save_model_settings = st.form_submit_button(t("lite_settings_save_models"), type="primary")

        if use_deepseek_defaults:
            updated_settings = dict(st.session_state.settings or {})
            updated_settings["base_url"] = str(base_url_value or "").strip() or "https://api.siliconflow.cn/v1"
            updated_settings["model"] = DEFAULT_SUMMARY_MODEL
            updated_settings["summary_model"] = DEFAULT_SUMMARY_MODEL
            updated_settings["fact_check_model"] = DEFAULT_FACT_CHECK_MODEL
            st.session_state.settings = updated_settings
            st.session_state.base_url = updated_settings["base_url"]
            st.session_state.model = DEFAULT_SUMMARY_MODEL
            st.session_state.summary_model = DEFAULT_SUMMARY_MODEL
            st.session_state.fact_check_model = DEFAULT_FACT_CHECK_MODEL
            st.session_state.last_saved_settings.update(
                {
                    "base_url": updated_settings["base_url"],
                    "model": DEFAULT_SUMMARY_MODEL,
                    "summary_model": DEFAULT_SUMMARY_MODEL,
                    "fact_check_model": DEFAULT_FACT_CHECK_MODEL,
                }
            )
            save_settings(updated_settings)
            st.success(t("lite_settings_use_defaults_success"))
            st.rerun()

        if save_model_settings:
            updated_settings = dict(st.session_state.settings or {})
            updated_api_key = str(api_key_value or "").strip()
            updated_base_url = str(base_url_value or "").strip() or "https://api.openai.com/v1"
            updated_summary_model = str(summary_model_value or "").strip() or DEFAULT_SUMMARY_MODEL
            updated_fact_check_model = str(fact_check_model_value or "").strip() or updated_summary_model
            
            updated_settings["api_key"] = updated_api_key
            updated_settings["base_url"] = updated_base_url
            updated_settings["model"] = updated_summary_model
            updated_settings["summary_model"] = updated_summary_model
            updated_settings["fact_check_model"] = updated_fact_check_model
            
            st.session_state.settings = updated_settings
            st.session_state.api_key = updated_api_key or os.environ.get("OPENAI_API_KEY", "")
            st.session_state.base_url = updated_base_url
            st.session_state.model = updated_summary_model
            st.session_state.summary_model = updated_summary_model
            st.session_state.fact_check_model = updated_fact_check_model
            st.session_state.last_saved_settings.update(
                {
                    "api_key": updated_api_key,
                    "base_url": updated_base_url,
                    "model": updated_summary_model,
                    "summary_model": updated_summary_model,
                    "fact_check_model": updated_fact_check_model,
                }
            )
            save_settings(updated_settings)
            st.success(t("lite_settings_save_success"))
            st.rerun()

    if is_admin_user():
        with st.expander(t("lite_settings_diag_manage"), expanded=False):
            st.caption(t("lite_settings_diag_manage_caption"))
            render_settings_diagnostics_page(
                task_status_value,
                task_logs,
                task_runs,
                task_run_items,
                show_header=False,
            )

            st.divider()
            with st.expander(t("lite_settings_view_task_center"), expanded=False):
                render_task_center_page(current_bg_task_id, current_bg_task_status, show_header=False)

            with st.expander(t("lite_settings_view_automation"), expanded=False):
                render_automation_page(show_header=False)


current_bg_task_id, current_bg_task_status = render_background_task_status_panel()
task_status_value = (current_bg_task_status or {}).get("status") or "idle"
_task_settings, _task_defs, task_logs, task_runs, task_run_items, _task_processed_ids = _load_scheduled_state()


# ==========================
# Lite 首页
# ==========================
with tab_home:
    render_processing_center_page(current_bg_task_id, current_bg_task_status)


# ==========================
# 历史记录
# ==========================
with tab_history:
    render_library_page(show_header=True)

# ==========================
# 留言板
# ==========================
with tab_wishwall:
    render_wish_wall_page(task_logs, task_runs, task_run_items)

# ==========================
# 设置与高级功能
# ==========================
with tab_settings:
    render_lite_settings_page(
        current_bg_task_id,
        current_bg_task_status,
        task_status_value,
        task_logs,
        task_runs,
        task_run_items,
    )
