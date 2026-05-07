import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core_logic import summarize_text  # type: ignore


def main() -> None:
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    api_key = str(settings.get("api_key") or "").strip()
    base_url = str(settings.get("base_url") or "").strip()
    proxy = str(settings.get("proxy") or "").strip() or None
    results_path = ROOT / "model_compare" / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
    existing = {str(item.get("model") or "") for item in results if isinstance(item, dict)}

    text = (
        "近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，"
        "并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，"
        "相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。"
    )

    candidate_models = [
        "Pro/moonshotai/Kimi-K2.6",
        "Pro/zai-org/GLM-5.1",
        "Pro/MiniMaxAI/MiniMax-M2.5",
    ]

    for model in candidate_models:
        if model in existing:
            print(f"skip: {model}")
            continue
        started = time.time()
        item = {"model": model}
        try:
            result = summarize_text(
                text=text,
                api_key=api_key,
                base_url=base_url,
                model=model,
                proxy_url=proxy,
                stream=False,
            )
            raw_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            item["elapsed_seconds"] = round(time.time() - started, 2)
            item["raw_result"] = raw_str
            try:
                parsed = json.loads(raw_str)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                summary_md = str(parsed.get("summary_markdown") or parsed.get("summary") or "").strip()
                fact_md = str(parsed.get("fact_check_markdown") or parsed.get("fact_check") or "").strip()
            else:
                summary_md = ""
                fact_md = ""
            item["summary_markdown"] = summary_md
            item["fact_check_markdown"] = fact_md
            item["summary_len"] = len(summary_md)
            item["fact_len"] = len(fact_md)
            item["fact_item_count"] = fact_md.count("### 条目")
        except Exception as e:
            item["elapsed_seconds"] = round(time.time() - started, 2)
            item["error"] = repr(e)

        results.append(item)
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"done: {model} ({item.get('elapsed_seconds')}s)")


if __name__ == "__main__":
    main()
