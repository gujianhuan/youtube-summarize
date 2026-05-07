import json
import sys
import time
from pathlib import Path
sys.path.insert(0, r'd:\Workspace\YouTubeSummarizer')
from core_logic import summarize_text

settings = json.load(open(r'd:\Workspace\YouTubeSummarizer\settings.json', 'r', encoding='utf-8'))
api_key = str(settings.get('api_key') or '')
base_url = str(settings.get('base_url') or '')
proxy = str(settings.get('proxy') or '') or None

text = """近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。""".strip()

models = [
    'deepseek-ai/DeepSeek-V3.2',
    'Pro/deepseek-ai/DeepSeek-V3.2',
    'Pro/moonshotai/Kimi-K2.6',
    'Pro/zai-org/GLM-5.1',
    'Pro/MiniMaxAI/MiniMax-M2.5',
    'Qwen/Qwen3-235B-A22B-Instruct-2507',
    'Qwen/Qwen3.5-397B-A17B',
]

results = []
out_path = Path(r'd:\Workspace\YouTubeSummarizer\model_compare_results.json')
for model in models:
    started = time.time()
    item = {'model': model}
    try:
        result = summarize_text(
            text=text,
            api_key=api_key,
            base_url=base_url,
            model=model,
            proxy_url=proxy,
            stream=False,
        )
        elapsed = round(time.time() - started, 2)
        item['elapsed_seconds'] = elapsed
        item['raw_result'] = result if isinstance(result, str) else str(result)
        try:
            parsed = json.loads(item['raw_result']) if isinstance(item['raw_result'], str) else result
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            summary_md = str(parsed.get('summary_markdown') or parsed.get('summary') or '').strip()
            fact_md = str(parsed.get('fact_check_markdown') or parsed.get('fact_check') or '').strip()
            item['summary_markdown'] = summary_md
            item['fact_check_markdown'] = fact_md
            item['summary_len'] = len(summary_md)
            item['fact_len'] = len(fact_md)
            item['fact_item_count'] = fact_md.count('### 条目')
        else:
            item['summary_markdown'] = ''
            item['fact_check_markdown'] = ''
            item['summary_len'] = 0
            item['fact_len'] = 0
            item['fact_item_count'] = 0
    except Exception as e:
        item['elapsed_seconds'] = round(time.time() - started, 2)
        item['error'] = repr(e)
    results.append(item)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

print(f'saved={out_path}')
print(f'count={len(results)}')
