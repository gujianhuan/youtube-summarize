import json
import re
import time
from pathlib import Path
import sys

# Make repo importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core_logic import summarize_text  # type: ignore


def _sanitize(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.:/+-]+", "_", name.strip())
    s = s.replace("/", "__")
    return s[:120]


def main() -> None:
    settings_path = ROOT / "settings.json"
    if not settings_path.exists():
        print(f"settings.json not found at {settings_path}")
        sys.exit(1)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    api_key = str(settings.get("api_key") or "").strip()
    base_url = str(settings.get("base_url") or "").strip()
    proxy = str(settings.get("proxy") or "").strip() or None

    # A realistic finance-news style sample to exercise both summary and fact-check
    test_text = (
        "近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，"
        "并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，"
        "相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。"
    )

    # Candidate models available via SiliconFlow API (based on available_models.txt and common top-tier choices)
    candidate_models = [
        "deepseek-ai/DeepSeek-V3.2",
        "Pro/deepseek-ai/DeepSeek-V3.2",
        "Pro/deepseek-ai/DeepSeek-V4-Flash",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "Qwen/Qwen3.5-397B-A17B",
        "Qwen/Qwen2.5-72B-Instruct",
        "Pro/moonshotai/Kimi-K2.6",
        "Pro/zai-org/GLM-5.1",
        "Pro/MiniMaxAI/MiniMax-M2.5",
    ]

    out_dir = ROOT / "model_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.json"

    results = []
    for model in candidate_models:
        started = time.time()
        item = {"model": model}
        try:
            result = summarize_text(
                text=test_text,
                api_key=api_key,
                base_url=base_url,
                model=model,
                proxy_url=proxy,
                stream=False,
            )
            elapsed = round(time.time() - started, 2)
            item["elapsed_seconds"] = elapsed
            raw_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            item["raw_result"] = raw_str
            try:
                parsed = json.loads(raw_str)
            except Exception:
                parsed = None

            if isinstance(parsed, dict):
                summary_md = str(parsed.get("summary_markdown") or parsed.get("summary") or "").strip()
                fact_md = str(parsed.get("fact_check_markdown") or parsed.get("fact_check") or "").strip()
            else:
                # Fallback: store raw only
                summary_md, fact_md = "", ""

            item["summary_markdown"] = summary_md
            item["fact_check_markdown"] = fact_md
            item["summary_len"] = len(summary_md)
            item["fact_len"] = len(fact_md)
            item["fact_item_count"] = fact_md.count("### 条目")

            # Persist pretty combined markdown for manual review
            combined_md = []
            combined_md.append(f"# 模型：{model}")
            combined_md.append("")
            combined_md.append("## 总结")
            combined_md.append(summary_md or "(空)")
            combined_md.append("")
            combined_md.append("## 事实核查")
            combined_md.append(fact_md or "(空)")
            (out_dir / f"{_sanitize(model)}.md").write_text("\n".join(combined_md), encoding="utf-8")

        except Exception as e:
            item["elapsed_seconds"] = round(time.time() - started, 2)
            item["error"] = repr(e)

        results.append(item)
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"done: {model} ({item.get('elapsed_seconds', '?')}s)")

    # Sort a quick view by fact_item_count desc, then fact_len desc, then summary_len desc
    ranked = sorted(
        results,
        key=lambda x: (int(x.get("fact_item_count") or 0), int(x.get("fact_len") or 0), int(x.get("summary_len") or 0)),
        reverse=True,
    )
    (out_dir / "ranked_top.txt").write_text(
        "\n".join(
            f"{i+1}. {r.get('model')} | fact_items={r.get('fact_item_count')} | "
            f"fact_len={r.get('fact_len')} | sum_len={r.get('summary_len')} | "
            f"time={r.get('elapsed_seconds')}s{' | ERR' if r.get('error') else ''}"
            for i, r in enumerate(ranked)
        ),
        encoding="utf-8",
    )
    print(f"saved: {results_path}")
    print(f"ranked: {(out_dir / 'ranked_top.txt')}")


if __name__ == "__main__":
    main()
