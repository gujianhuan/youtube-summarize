import json
import sys
from pathlib import Path
log = Path(r"D:\Workspace\YouTubeSummarizer\fact_check_case_stage.log")
log.write_text("stage:boot\n", encoding="utf-8")
sys.path.insert(0, r"D:\Workspace\YouTubeSummarizer")
from core_logic import summarize_text
log.write_text(log.read_text(encoding="utf-8") + "stage:imported\n", encoding="utf-8")
settings = json.load(open(r"D:\Workspace\YouTubeSummarizer\settings.json", "r", encoding="utf-8"))
log.write_text(log.read_text(encoding="utf-8") + "stage:settings_loaded\n", encoding="utf-8")
text = "近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。"
log.write_text(log.read_text(encoding="utf-8") + "stage:before_call\n", encoding="utf-8")
result = summarize_text(text=text, api_key=str(settings.get("api_key") or ""), base_url=str(settings.get("base_url") or ""), model=str(settings.get("model") or ""), proxy_url=str(settings.get("proxy") or "") or None, stream=False)
log.write_text(log.read_text(encoding="utf-8") + "stage:after_call\n", encoding="utf-8")
Path(r"D:\Workspace\YouTubeSummarizer\fact_check_case_output_3.txt").write_text(str(result), encoding="utf-8")
log.write_text(log.read_text(encoding="utf-8") + "stage:output_saved\n", encoding="utf-8")
