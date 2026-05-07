import json
import sys
sys.path.insert(0, r"D:\Workspace\YouTubeSummarizer")
from core_logic import summarize_text
settings = json.load(open(r"D:\Workspace\YouTubeSummarizer\settings.json", "r", encoding="utf-8"))
text = """
近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。
""".strip()
result = summarize_text(
    text=text,
    api_key=str(settings.get("api_key") or ""),
    base_url=str(settings.get("base_url") or ""),
    model=str(settings.get("model") or ""),
    proxy_url=str(settings.get("proxy") or "") or None,
    stream=False,
)
out = r"D:\Workspace\YouTubeSummarizer\fact_check_case_output_2.txt"
with open(out, "w", encoding="utf-8") as fh:
    if isinstance(result, str):
        fh.write(result)
    else:
        fh.write(str(result))
print("fact_check_saved_2")
