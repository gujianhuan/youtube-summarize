"""
Windows GUI 启动包装器。

用 .pyw 启动本地转写助手 GUI，避免弹出命令行窗口；
如果启动失败，则弹出错误框，避免用户双击后“没有反应”。
"""

from __future__ import annotations

import traceback
import tkinter as tk
from tkinter import messagebox


def main() -> int:
    try:
        from video_local_helper_gui import main as run_gui

        return int(run_gui() or 0)
    except Exception:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "本地转写助手启动失败",
            "GUI 启动失败，请检查 Python 环境和依赖。\n\n"
            f"{traceback.format_exc()}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
