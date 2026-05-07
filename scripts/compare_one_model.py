import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core_logic import summarize_text  # type: ignore


def _sanitize(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.:/+-]+", "_", name.strip())
    return s.replace("/", "__")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: compare_one_model.py <model_name>")
        sys.exit(1)

    model = sys.argv[1].strip()
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    api_key = str(settings.get("api_key") or "").strip()
    base_url = str(settings.get("base_url") or "").strip()
    proxy = str(settings.get("proxy") or "").strip() or None

    text = (
        "近期财经舆论关注两条消息。其一，有报道提到布伦特原油价格在2026年4月达到120美元，"
        "并援引路透社和彭博社相关报道。其二，台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市，"
        "相关说法提到了台湾证券交易所与媒体报道。另有评论文章引用了美丽岛电子报页面。"
    )

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
            item["summary_markdown"] = str(parsed.get("summary_markdown") or parsed.get("summary") or "").strip()
            item["fact_check_markdown"] = str(parsed.get("fact_check_markdown") or parsed.get("fact_check") or "").strip()
        else:
            item["summary_markdown"] = ""
            item["fact_check_markdown"] = ""
        item["summary_len"] = len(item["summary_markdown"])
        item["fact_len"] = len(item["fact_check_markdown"])
        item["fact_item_count"] = item["fact_check_markdown"].count("### 条目")
    except Exception as e:
        item["elapsed_seconds"] = round(time.time() - started, 2)
        item["error"] = repr(e)

    out_dir = ROOT / "model_compare_single"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{_sanitize(model)}.json"
    out_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
