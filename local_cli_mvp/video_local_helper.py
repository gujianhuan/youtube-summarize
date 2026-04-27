"""
本地转写助手 CLI 入口。

瘦身版仅保留最小本地转写闭环：
- yt-dlp 下载音频
- faster-whisper CPU 转写
- 可选上传 bridge 并打开主站
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portable_runtime import configure_portable_environment
from local_cli_mvp.local_helper_core import (
    DEFAULT_BRIDGE_API_URL,
    DEFAULT_MAIN_URL,
    DEFAULT_OUT_DIR,
    LocalHelperConfig,
    format_local_helper_error,
    result_to_json,
    run_local_helper,
)


configure_portable_environment()


def parse_args():
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="本地视频 transcript 助手（瘦身版）")
    parser.add_argument("url", help="YouTube 或 Bilibili 视频链接/ID")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="输出目录")
    parser.add_argument("--languages", default="zh-Hans,zh,en", help="优先语言，逗号分隔")
    parser.add_argument("--cookies-browser", default="auto", help="浏览器 cookies 来源，如 auto/chrome/edge/firefox")
    parser.add_argument("--cookies-file", default="", help="可选 cookies 文件")
    parser.add_argument("--timeout", type=float, default=180.0, help="整体超时时间（秒）")
    parser.add_argument("--retries", type=int, default=1, help="重试次数")
    parser.add_argument("--asr-model", default="base", help="Whisper 模型，如 tiny/base/small")
    parser.add_argument("--push-to-main", action="store_true", help="转写完成后上传 bridge payload 并打开主站")
    parser.add_argument("--main-url", default=DEFAULT_MAIN_URL, help="主站地址")
    parser.add_argument("--bridge-api-url", default=DEFAULT_BRIDGE_API_URL, help="Bridge API 地址")
    parser.add_argument("--bridge-api-token", default=os.environ.get("BRIDGE_API_TOKEN", ""), help="Bridge API Token")
    parser.add_argument("--no-open-browser", action="store_true", help="上传成功后不自动打开主站")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> LocalHelperConfig:
    """将命令行参数转成统一配置对象。"""

    return LocalHelperConfig(
        url=args.url,
        out_dir=args.out_dir,
        languages=args.languages,
        cookies_browser=args.cookies_browser,
        cookies_file=args.cookies_file,
        timeout=float(args.timeout),
        retries=int(args.retries),
        asr_model=args.asr_model,
        asr_force_cpu=True,
        push_to_main=bool(args.push_to_main),
        main_url=args.main_url,
        bridge_api_url=args.bridge_api_url,
        bridge_api_token=args.bridge_api_token,
        no_open_browser=bool(args.no_open_browser),
    )


def main():
    """CLI 主入口。"""

    args = parse_args()
    config = config_from_args(args)
    try:
        result_payload = run_local_helper(config)
        print(result_to_json(result_payload))
        return 0
    except Exception as exc:
        print(result_to_json({"ok": False, "error": format_local_helper_error(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
