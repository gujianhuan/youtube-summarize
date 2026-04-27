"""
Windows 便携版 GUI 入口。

负责在 exe 启动时初始化资源路径、日志目录和错误提示，确保普通用户
双击后即使失败也能看到明确的诊断信息。
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


if not getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from portable_runtime import configure_portable_environment, get_logs_dir


def configure_logging() -> Path:
    """初始化便携版日志配置并返回日志文件路径。"""

    logs_dir = get_logs_dir(create=True)
    log_file = logs_dir / "local_helper_portable.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
    )
    logging.info("Portable launcher started")
    return log_file


def main() -> int:
    """启动便携版 GUI。"""

    runtime_info = configure_portable_environment()
    log_file = configure_logging()
    logging.info("Runtime info: %s", runtime_info)

    try:
        os.chdir(runtime_info["runtime_root"])
        from video_local_helper_gui import main as run_gui

        return int(run_gui() or 0)
    except Exception:
        logging.exception("Portable GUI startup failed")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "本地转写助手启动失败",
            "便携版启动失败，请把 logs 目录里的日志一起发给开发者排查。\n\n"
            f"日志文件：{log_file}\n\n"
            f"{traceback.format_exc()}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
