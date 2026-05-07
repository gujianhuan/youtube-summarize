import json
import sys
from pathlib import Path
sys.path.insert(0, r"D:\Workspace\YouTubeSummarizer")
from core_logic import summarize_text
settings = json.load(open(r"D:\Workspace\YouTubeSummarizer\settings.json", "r", encoding="utf-8"))
text = (
    "近期财经舆论聚焦两条消息。第一，有市场报道提到布伦特原油价格在2026年4月达到120美元，"
    "并称路透社、彭博社相关链接可作为参考。第二，台湾股市总市值达到4.47万亿美元，"
    "超越加拿大成为全球第六大股市，相关说法提到了台湾证券交易所与外部财经媒体。"
    "另有评论文章引用了美丽岛电子报页面。"
)
result = summarize_text(
    text=text,
    api_key=str(settings.get("api_key") or ""),
    base_url=str(settings.get("base_url") or ""),
    model=str(settings.get("model") or ""),
    proxy_url=str(settings.get("proxy") or "") or None,
    stream=False,
)
Path(r"D:\Workspace\YouTubeSummarizer\fact_check_render_verify.txt").write_text(str(result), encoding="utf-8")
print("saved")
