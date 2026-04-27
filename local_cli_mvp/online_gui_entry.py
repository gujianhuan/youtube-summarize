"""
Windows 在线安装版 GUI 入口。

首包只携带 GUI 启动器，首次启动时自动下载完整瘦身运行包。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


if not getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from local_cli_mvp.online_runtime_installer import (
    ensure_online_runtime,
    get_runtime_dirs,
    is_runtime_ready,
    load_runtime_manifest,
)


def configure_logging() -> Path:
    """初始化在线安装版日志配置。"""

    runtime_dirs = get_runtime_dirs()
    runtime_dirs["logs"].mkdir(parents=True, exist_ok=True)
    log_file = runtime_dirs["logs"] / "local_helper_online.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    logging.info("Online launcher started")
    return log_file


def _show_install_message(message: str) -> None:
    """通过消息框提示安装进度。"""

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("本地转写助手", message)
    root.destroy()


def main() -> int:
    """在线安装版 GUI 主入口。"""

    log_file = configure_logging()
    try:
        manifest = load_runtime_manifest()
        already_ready = is_runtime_ready(manifest)
        runtime_info = ensure_online_runtime(callback=logging.info)
        target_executable = str(runtime_info["target_executable"])

        if not already_ready:
            _show_install_message(
                "首次运行安装完成。\n\n"
                f"运行包目录：{runtime_info['runtime_root']}\n"
                f"日志目录：{runtime_info['logs_dir']}"
            )

        logging.info("Launching installed runtime executable: %s", target_executable)
        completed = subprocess.run(
            [target_executable],
            cwd=str(Path(target_executable).resolve().parent),
            check=False,
        )
        return int(completed.returncode or 0)
    except Exception:
        logging.exception("Online GUI startup failed")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "本地转写助手启动失败",
            "在线安装版启动失败，请把日志发给开发者。\n\n"
            f"日志文件：{log_file}\n\n"
            f"{traceback.format_exc()}",
        )
        root.destroy()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
