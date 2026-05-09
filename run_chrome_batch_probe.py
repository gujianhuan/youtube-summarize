import json
from pathlib import Path
from datetime import datetime

from run_chrome_page_extension_probe import run_probe

OUTPUT_DIR = Path(r"D:\Workspace\YouTubeSummarizer")
BATCH_SUMMARY_FILE = OUTPUT_DIR / "chrome_page_batch_summary.json"

DEFAULT_VIDEOS = [
    "https://www.youtube.com/watch?v=C14SVwWZ2fE",
    "https://www.youtube.com/watch?v=TDv56whosPQ",
    "https://www.youtube.com/watch?v=FIyzZoVLceo&t=6132s",
    "https://www.youtube.com/watch?v=brNEAlPN3zY",
    "https://www.youtube.com/watch?v=3W8w14IwAYY",
    "https://www.youtube.com/watch?v=G0o7ToVxOOs",
    "https://www.youtube.com/watch?v=4l97aNza_Zc",
]


def run_batch(urls: list[str]) -> dict:
    results = []
    for url in urls:
        try:
            res = run_probe(url)
        except Exception as e:
            res = {
                "video_url": url,
                "final_state": "exception",
                "error": str(e),
            }
        results.append(res)
    summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "count": len(results),
        "results": results,
    }
    BATCH_SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import sys

    urls = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_VIDEOS
    out = run_batch(urls)
    print(json.dumps(out, ensure_ascii=False, indent=2))
