"""
本地转写助手 GUI。

使用 tkinter 提供一个可双击打开的极简界面，复用 `video_local_helper.py`
中的核心处理逻辑，完成：

1. 输入视频链接
2. 本地转写
3. 可选上传主站并自动打开
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from video_local_helper import DEFAULT_OUT_DIR, LocalHelperConfig, run_local_helper


class LocalHelperGuiApp:
    """本地转写助手 GUI 应用。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("本地转写助手")
        self.root.geometry("860x700")
        self.root.minsize(760, 620)

        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.url_var = tk.StringVar()
        self.cookies_browser_var = tk.StringVar(value="auto")
        self.cookies_file_var = tk.StringVar()
        self.languages_var = tk.StringVar(value="zh-Hans,zh,en")
        self.asr_model_var = tk.StringVar(value="base")
        self.out_dir_var = tk.StringVar(value=DEFAULT_OUT_DIR)
        self.main_url_var = tk.StringVar(value="https://youtube-summarize-0oms.onrender.com/")
        self.bridge_api_url_var = tk.StringVar(value="https://youtube-summarize-bridge.onrender.com")
        self.bridge_api_token_var = tk.StringVar()

        self.push_to_main_var = tk.BooleanVar(value=True)
        self.open_browser_var = tk.BooleanVar(value=True)
        self.asr_force_cpu_var = tk.BooleanVar(value=False)

        self.status_var = tk.StringVar(value="等待开始")

        self._build_ui()
        self._poll_queue()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        container = ttk.Frame(self.root, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="本地转写助手", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            container,
            text="轻量版仅保留本地下载、CPU 转写与可选主站上传，适合发给普通用户测试。",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 16))

        current_row = 2

        current_row = self._add_labeled_entry(container, current_row, "视频链接", self.url_var, width=90)
        current_row = self._add_labeled_entry(container, current_row, "输出目录", self.out_dir_var, width=90)
        current_row = self._add_labeled_entry(container, current_row, "优先语言", self.languages_var)
        current_row = self._add_labeled_entry(container, current_row, "Cookies 浏览器", self.cookies_browser_var)
        current_row = self._add_labeled_entry(container, current_row, "Cookies 文件", self.cookies_file_var)
        current_row = self._add_labeled_entry(container, current_row, "Whisper 模型", self.asr_model_var)
        current_row = self._add_labeled_entry(container, current_row, "主站地址", self.main_url_var, width=90)
        current_row = self._add_labeled_entry(container, current_row, "Bridge 地址", self.bridge_api_url_var, width=90)
        current_row = self._add_labeled_entry(container, current_row, "Bridge Token", self.bridge_api_token_var, width=90, show="*")

        options_frame = ttk.LabelFrame(container, text="选项", padding=12)
        options_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(6, 12))
        options_frame.columnconfigure(0, weight=1)
        options_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(options_frame, text="转写完成后上传主站", variable=self.push_to_main_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(options_frame, text="上传成功后自动打开浏览器", variable=self.open_browser_var).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Checkbutton(options_frame, text="固定使用 CPU 转写（轻量版）", variable=self.asr_force_cpu_var).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        current_row += 1

        action_frame = ttk.Frame(container)
        action_frame.grid(row=current_row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        action_frame.columnconfigure(1, weight=1)

        self.start_button = ttk.Button(action_frame, text="开始转写", command=self._start_processing)
        self.start_button.grid(row=0, column=0, sticky="w")
        ttk.Label(action_frame, textvariable=self.status_var).grid(row=0, column=1, sticky="w", padx=(14, 0))

        current_row += 1

        log_frame = ttk.LabelFrame(container, text="运行日志", padding=8)
        log_frame.grid(row=current_row, column=0, columnspan=3, sticky="nsew")
        container.rowconfigure(current_row, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=18, font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        current_row += 1

        result_frame = ttk.LabelFrame(container, text="最近结果", padding=8)
        result_frame.grid(row=current_row, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, height=10, font=("Consolas", 10))
        self.result_text.grid(row=0, column=0, sticky="nsew")
        self.result_text.configure(state="disabled")

    def _add_labeled_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        width: int = 50,
        show: str | None = None,
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=width, show=show or "")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4, padx=(12, 0))
        return row + 1

    def _append_text(self, widget: scrolledtext.ScrolledText, message: str) -> None:
        widget.configure(state="normal")
        widget.insert(tk.END, message.rstrip() + "\n")
        widget.see(tk.END)
        widget.configure(state="disabled")

    def _log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _set_status(self, message: str) -> None:
        self.log_queue.put(("status", message))

    def _set_result(self, payload: dict) -> None:
        self.log_queue.put(("result", json.dumps(payload, ensure_ascii=False, indent=2)))

    def _processing_done(self) -> None:
        self.log_queue.put(("done", "处理完成"))

    def _processing_failed(self, message: str) -> None:
        self.log_queue.put(("error", message))

    def _build_config(self) -> LocalHelperConfig:
        return LocalHelperConfig(
            url=self.url_var.get().strip(),
            out_dir=self.out_dir_var.get().strip() or DEFAULT_OUT_DIR,
            languages=self.languages_var.get().strip() or "zh-Hans,zh,en",
            cookies_browser=self.cookies_browser_var.get().strip() or "auto",
            cookies_file=self.cookies_file_var.get().strip(),
            asr_model=self.asr_model_var.get().strip() or "base",
            asr_force_cpu=bool(self.asr_force_cpu_var.get()),
            push_to_main=bool(self.push_to_main_var.get()),
            main_url=self.main_url_var.get().strip() or "https://youtube-summarize-0oms.onrender.com/",
            bridge_api_url=self.bridge_api_url_var.get().strip() or "https://youtube-summarize-bridge.onrender.com",
            bridge_api_token=self.bridge_api_token_var.get().strip(),
            no_open_browser=not bool(self.open_browser_var.get()),
        )

    def _start_processing(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("提示", "当前已有任务在运行，请等待完成。")
            return

        config = self._build_config()
        if not config.url:
            messagebox.showwarning("缺少链接", "请先输入 YouTube 或 Bilibili 视频链接。")
            return

        self.start_button.configure(state="disabled")
        self.status_var.set("正在处理，请稍候...")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.configure(state="disabled")

        self.worker_thread = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        self.worker_thread.start()

    def _run_worker(self, config: LocalHelperConfig) -> None:
        try:
            result = run_local_helper(config, log_callback=self._log)
            self._set_result(result)
            self._processing_done()
        except Exception as exc:
            self._processing_failed(str(exc))

    def _poll_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.log_queue.get_nowait()
                if event_type == "log":
                    self._append_text(self.log_text, payload)
                elif event_type == "status":
                    self.status_var.set(payload)
                elif event_type == "result":
                    self.result_text.configure(state="normal")
                    self.result_text.delete("1.0", tk.END)
                    self.result_text.insert("1.0", payload)
                    self.result_text.configure(state="disabled")
                elif event_type == "done":
                    self.status_var.set(payload)
                    self.start_button.configure(state="normal")
                elif event_type == "error":
                    self.status_var.set("处理失败")
                    self.start_button.configure(state="normal")
                    self._append_text(self.log_text, f"[error] {payload}")
                    messagebox.showerror("处理失败", payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._poll_queue)


def main() -> int:
    root = tk.Tk()
    app = LocalHelperGuiApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
