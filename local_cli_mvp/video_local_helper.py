import argparse
import json
import os
import sys
from pathlib import Path

from core_logic import build_api, format_error, get_transcript_from_input, get_video_transcript, summarize_text


def parse_args():
    parser = argparse.ArgumentParser(description="本地视频 transcript / 总结助手 MVP")
    parser.add_argument("url", help="YouTube 或 Bilibili 视频链接/ID")
    parser.add_argument("--out-dir", default="local_cli_mvp_output", help="输出目录")
    parser.add_argument("--languages", default="zh-Hans,zh,en", help="优先语言，逗号分隔")
    parser.add_argument("--cookies-browser", default="auto", help="浏览器 cookies 来源，如 auto/chrome/edge/firefox")
    parser.add_argument("--cookies-file", default="", help="可选 cookies 文件")
    parser.add_argument("--timeout", type=float, default=180.0, help="整体超时时间（秒）")
    parser.add_argument("--retries", type=int, default=1, help="重试次数")
    parser.add_argument("--asr-model", default="base", help="Whisper 模型，如 tiny/base/small")
    parser.add_argument("--asr-force-cpu", action="store_true", help="强制 CPU 转写")
    parser.add_argument("--summary", action="store_true", help="抓到 transcript 后顺手生成总结")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"), help="总结模型名")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"), help="OpenAI 兼容接口地址")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""), help="OpenAI 兼容 API Key")
    return parser.parse_args()


def safe_name(text: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text.strip())
    return value[:80] or "transcript"


def main():
    args = parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 强制走本地链路，不使用 Render 远程节点/tunnel
    os.environ["LOCAL_FETCH_NODE_MODE"] = "1"
    os.environ["REMOTE_TRANSCRIBE_MODE"] = ""

    try:
        video_id, video_url, languages_effective = get_transcript_from_input(args.url, args.languages)
        api = build_api(proxy_url="", timeout_seconds=float(args.timeout), use_system_proxy=False, retries=int(args.retries))
        setattr(api, "_cookies_file", args.cookies_file.strip())
        setattr(api, "_cookies_content", "")
        setattr(api, "_cookies_content_b64", "")
        setattr(api, "_cookies_from_browser", args.cookies_browser.strip())
        setattr(api, "_asr_enabled", True)
        setattr(api, "_asr_model", args.asr_model.strip() or "base")
        setattr(api, "_asr_language", "auto")
        setattr(api, "_asr_fast_mode", True)
        setattr(api, "_asr_force_cpu", bool(args.asr_force_cpu))
        setattr(api, "_status_callback", lambda msg: print(f"[status] {msg}"))

        transcript = get_video_transcript(
            api=api,
            video_id=video_id,
            video_url=video_url,
            languages=[part.strip() for part in languages_effective.split(",") if part.strip()],
        )
        base_name = safe_name(video_id or video_url)
        transcript_path = out_dir / f"{base_name}.transcript.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "video_id": video_id,
            "video_url": video_url,
            "transcript_file": str(transcript_path),
        }, ensure_ascii=False, indent=2))

        if args.summary:
            if not args.api_key.strip():
                print("[warn] 未提供 API Key，跳过总结。")
                return 0
            summary = summarize_text(
                transcript,
                api_key=args.api_key.strip(),
                base_url=args.base_url.strip(),
                model=args.model.strip(),
                proxy_url=None,
                stream=False,
            )
            summary_path = out_dir / f"{base_name}.summary.json"
            summary_path.write_text(summary, encoding="utf-8")
            print(json.dumps({
                "ok": True,
                "summary_file": str(summary_path),
            }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": format_error(exc),
        }, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
