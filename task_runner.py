import threading
import time
import logging
import uuid

# 修改导入，不从 app 依赖未抽离的 internal 函数，而是直接调 core_logic
from core_logic import get_transcript_from_input, get_video_transcript, is_html_like_text, summarize_text, build_api, get_effective_proxy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局任务状态字典（简单内存缓存，重启会丢失）
# 格式: { "task_id": {"status": "queued|running|success|failed", "url": "...", "result": "...", "error": ""} }
TASK_STATUS_DB = {}

def _background_worker(video_url, task_id, model_selected, proxy_input, use_system_proxy, api_key, base_url, settings):
    """
    这是后台真正干活的函数，执行耗时任务
    """
    logger.info(f"[Task {task_id}] 开始处理视频: {video_url}")
    TASK_STATUS_DB[task_id]["status"] = "running"
    
    try:
        # --- 1. 抓取阶段 (复刻 app.py 里的 internal_fetch_transcript 逻辑) ---
        logger.info(f"[Task {task_id}] 正在抓取字幕...")
        
        eff_proxy, _ = get_effective_proxy(proxy_input, use_system_proxy)
        api = build_api(eff_proxy, 60.0, use_system_proxy, 1)
        
        # 解析 URL
        video_id, langs_list, v_url = get_transcript_from_input(video_url, ["zh-Hans", "zh-Hant", "zh-TW", "zh", "en", "ja", "ko"])
        
        # 抓取文本
        text = get_video_transcript(api, video_id, video_url=v_url, languages=langs_list)
        if is_html_like_text(text):
            raise Exception("检测到返回内容为 HTML 页面源码，无法用于总结。请确认视频可访问，或更换网络/代理后重试。")
            
        if not text:
             raise Exception("未获取到字幕内容")

        # --- 2. 总结阶段 (复刻 app.py 里的 internal_summarize 逻辑) ---
        logger.info(f"[Task {task_id}] 抓取成功，开始 AI 总结...")
        
        if not api_key:
            raise Exception("未提供 API Key")
            
        summary = summarize_text(
            text,
            api_key,
            base_url,
            model_name=model_selected,
            proxy_url=eff_proxy,
            stream=False  # 后台任务默认不使用流式
        )

        logger.info(f"[Task {task_id}] 处理成功!")
        TASK_STATUS_DB[task_id]["status"] = "success"
        TASK_STATUS_DB[task_id]["result"] = summary
        
    except Exception as e:
        logger.error(f"[Task {task_id}] 处理发生异常: {e}")
        TASK_STATUS_DB[task_id]["status"] = "failed"
        TASK_STATUS_DB[task_id]["error"] = str(e)

def submit_task(video_url, model_selected, proxy_input, use_system_proxy, api_key, base_url, settings):
    """
    网页调用这个函数，瞬间返回，后台偷偷启动线程
    """
    task_id = str(uuid.uuid4())
    logger.info(f"收到新任务: {task_id}, URL: {video_url}")
    
    # 记录初始状态
    TASK_STATUS_DB[task_id] = {
        "status": "queued",
        "url": video_url,
        "result": "",
        "error": ""
    }
    
    # 把任务丢给一个独立的线程去跑
    thread = threading.Thread(
        target=_background_worker, 
        args=(video_url, task_id, model_selected, proxy_input, use_system_proxy, api_key, base_url, settings)
    )
    # 设置为守护线程，网页服务关了它也跟着关
    thread.daemon = True
    thread.start()
    
    return task_id

def get_task_status(task_id):
    """
    网页定时调用这个函数查询任务进度
    """
    return TASK_STATUS_DB.get(task_id, {"status": "not_found", "error": "任务不存在或已过期"})
