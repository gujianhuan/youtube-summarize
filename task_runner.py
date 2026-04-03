import threading
import time
import logging
import uuid

# 假设这里会用到你的核心逻辑
from core_logic import get_effective_proxy, check_network, internal_fetch_transcript, internal_summarize

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
        # 1. 抓取阶段
        logger.info(f"[Task {task_id}] 正在抓取字幕...")
        text, err = internal_fetch_transcript(video_url, progress_callback=None)
        
        if err:
            logger.error(f"[Task {task_id}] 抓取失败: {err}")
            TASK_STATUS_DB[task_id]["status"] = "failed"
            TASK_STATUS_DB[task_id]["error"] = f"抓取失败: {err}"
            return
            
        if not text:
             logger.error(f"[Task {task_id}] 未获取到字幕内容")
             TASK_STATUS_DB[task_id]["status"] = "failed"
             TASK_STATUS_DB[task_id]["error"] = "未获取到字幕内容"
             return

        # 2. 总结阶段
        logger.info(f"[Task {task_id}] 抓取成功，开始 AI 总结...")
        
        # 为了兼容 core_logic 的 summarize_text，可能需要处理流式或非流式
        # 简单起见，这里假设 internal_summarize 支持非流式调用
        summary, err_sum = internal_summarize(text, model_selected, api_key, base_url, proxy_input)
        
        if err_sum:
            logger.error(f"[Task {task_id}] 总结失败: {err_sum}")
            TASK_STATUS_DB[task_id]["status"] = "failed"
            TASK_STATUS_DB[task_id]["error"] = f"总结失败: {err_sum}"
            return

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
