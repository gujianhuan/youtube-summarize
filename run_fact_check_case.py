import json
import os
import sys
sys.path.insert(0, r"D:\Workspace\YouTubeSummarizer")
from core_logic import summarize_text
settings = json.load(open(r"D:\Workspace\YouTubeSummarizer\settings.json", "r", encoding="utf-8"))
text = """
这是一段财经资讯核查测试文本：
第一，市场消息称布伦特原油价格在2026年4月达到120美元，部分报道引用了路透社和彭博社相关链接。
第二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，相关说法提到台湾证券交易所与财经媒体报道。
第三，评论中还提到了美丽岛电子报的相关页面。
请对这些可核查说法做事实核查。
""".strip()
result = summarize_text(
    text=text,
    api_key=str(settings.get("api_key") or ""),
    base_url=str(settings.get("base_url") or ""),
    model=str(settings.get("model") or ""),
    proxy_url=str(settings.get("proxy") or "") or None,
    stream=False,
)
out = r"D:\Workspace\YouTubeSummarizer\fact_check_case_output.txt"
with open(out, "w", encoding="utf-8") as fh:
    if isinstance(result, str):
        fh.write(result)
    else:
        fh.write(str(result))
print("fact_check_saved")
