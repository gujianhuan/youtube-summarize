import asyncio
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import websockets


EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
APP_URL = "https://youtube-summarize-0oms.onrender.com/"
DEBUG_PORT = 9222
PROFILE_DIR = Path(r"D:\Workspace\YouTubeSummarizer\edge-profile-probe")
OUTPUT_DIR = Path(r"D:\Workspace\YouTubeSummarizer")
TRACE_FILE = OUTPUT_DIR / "page_probe_trace.log"

FACT_CHECK_SAMPLE = (
    "彭博社和路透社在2026年4月报道称，布伦特原油价格一度升至每桶120美元附近。"
    "另外，多家财经媒体和台湾证券交易所相关数据提到，台湾股市总市值达到4.47万亿美元，"
    "超过加拿大成为全球第六大股市。美丽岛电子报也刊登了相关评论。"
)


def _fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _trace(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n"
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line)


async def _cdp_send(ws, message_id: int, method: str, params: dict | None = None):
    payload = {"id": message_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("id") == message_id:
            return data


async def _runtime_eval(ws, message_id: int, expression: str, await_promise: bool = True):
    result = await _cdp_send(
        ws,
        message_id,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        },
    )
    return result.get("result", {}).get("result", {}).get("value")


async def _wait_for_tokens(ws, start_message_id: int, tokens: list[str], timeout_seconds: int = 90):
    message_id = start_message_id
    deadline = time.time() + timeout_seconds
    latest = False
    quoted_tokens = ", ".join(json.dumps(token, ensure_ascii=False) for token in tokens)
    while time.time() < deadline:
        latest = await _runtime_eval(
            ws,
            message_id,
            f'(() => {{ const text = (document.body && document.body.innerText) || ""; return [{quoted_tokens}].every(token => text.includes(token)); }})()',
            await_promise=False,
        )
        message_id += 1
        if bool(latest):
            return True, message_id
        await asyncio.sleep(1)
    return False, message_id


async def _read_text_snippet(ws, message_id: int, max_chars: int = 12000):
    snippet = await _runtime_eval(
        ws,
        message_id,
        f'(() => {{ const text = (document.body && document.body.innerText) || ""; return text.slice(0, {max_chars}); }})()',
        await_promise=False,
    )
    return str(snippet or "")


async def main():
    TRACE_FILE.write_text("", encoding="utf-8")
    _trace("probe_start")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _trace(f"profile_dir={PROFILE_DIR}")
    proc = subprocess.Popen(
        [
            EDGE_PATH,
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--headless",
            "--disable-gpu",
            "--window-size=1440,2400",
            APP_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _trace("edge_spawned")
        targets = []
        for _ in range(60):
            try:
                targets = _fetch_json(f"http://127.0.0.1:{DEBUG_PORT}/json/list")
                if targets:
                    _trace(f"targets_found={len(targets)}")
                    break
            except Exception:
                _trace("targets_retry")
                time.sleep(1)
        if not targets:
            raise RuntimeError("CDP targets not available")

        page_target = None
        for target in targets:
            if target.get("type") == "page" and "webSocketDebuggerUrl" in target:
                page_target = target
                break
        if not page_target:
            raise RuntimeError("No page target found")

        ws_url = page_target["webSocketDebuggerUrl"]
        _trace(f"ws_url={ws_url}")
        async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
            _trace("ws_connected")
            msg_id = 1
            await _cdp_send(ws, msg_id, "Page.enable")
            msg_id += 1
            await _cdp_send(ws, msg_id, "Runtime.enable")
            msg_id += 1
            _trace("cdp_enabled")

            ready_state = await _runtime_eval(ws, msg_id, "document.readyState", await_promise=False)
            msg_id += 1
            _trace(f"ready_state={ready_state}")

            try:
                initial_ready, msg_id = await _wait_for_tokens(
                    ws,
                    msg_id,
                    ["处理中心"],
                    timeout_seconds=45,
                )
                _trace(f"initial_ready={initial_ready}")
            except Exception as _:
                _trace("initial_ready_check_failed")
            try:
                initial_text = await _read_text_snippet(ws, msg_id, max_chars=8000)
                msg_id += 1
                (OUTPUT_DIR / "page_probe_initial.txt").write_text(str(initial_text or ""), encoding="utf-8")
                _trace(f"initial_text_len={len(str(initial_text or ''))}")
            except Exception as _:
                _trace("initial_text_dump_failed")

            click_text_tab_js = r"""
                (() => {
                  const btn = [...document.querySelectorAll("button")].find(el => (el.innerText || "").includes("粘贴文本"));
                  if (!btn) return "text_tab_not_found";
                  btn.click();
                  return "ok";
                })()
            """
            click_text_tab = await _runtime_eval(ws, msg_id, click_text_tab_js, await_promise=False)
            msg_id += 1
            _trace(f"click_text_tab={click_text_tab}")

            fill_textarea_js = json.dumps(
                FACT_CHECK_SAMPLE,
                ensure_ascii=False,
            )
            fill_textarea_expr = rf"""
                (() => {{
                  const area = [...document.querySelectorAll("textarea")].find(el => {{
                    const label = el.getAttribute("aria-label") || "";
                    const placeholder = el.getAttribute("placeholder") || "";
                    return label.includes("粘贴 transcript / 字幕文本") || placeholder.includes("把浏览器扩展提取到的字幕文本粘贴到这里");
                  }});
                  if (!area) return "textarea_not_found";
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                  setter.call(area, {fill_textarea_js});
                  area.dispatchEvent(new Event("input", {{ bubbles: true }}));
                  area.dispatchEvent(new Event("change", {{ bubbles: true }}));
                  return "ok";
                }})()
            """
            fill_status = await _runtime_eval(ws, msg_id, fill_textarea_expr, await_promise=False)
            msg_id += 1
            _trace(f"fill_status={fill_status}")

            click_summary_js = r"""
                (() => {
                  const btn = [...document.querySelectorAll("button")].find(el => (el.innerText || "").includes("总结字幕文本"));
                  if (!btn) return "summary_button_not_found";
                  btn.click();
                  return "ok";
                })()
            """
            click_summary = await _runtime_eval(ws, msg_id, click_summary_js, await_promise=False)
            msg_id += 1
            _trace(f"click_summary={click_summary}")

            try:
                final_ready, msg_id = await _wait_for_tokens(
                    ws,
                    msg_id,
                    ["字幕总结"],
                    timeout_seconds=240,
                )
                _trace(f"final_ready={final_ready}")
            except Exception as _:
                _trace("final_ready_check_failed")
            try:
                final_text = await _read_text_snippet(ws, msg_id, max_chars=20000)
                msg_id += 1
                (OUTPUT_DIR / "page_probe_final.txt").write_text(str(final_text or ""), encoding="utf-8")
                _trace(f"final_text_len={len(str(final_text or ''))}")
            except Exception as _:
                _trace("final_text_dump_failed")

            summary = {
                "click_text_tab": click_text_tab,
                "fill_status": fill_status,
                "click_summary": click_summary,
                "initial_has_render_info": "Render 部署信息" in str(initial_text or ""),
                "initial_has_commit": "commit=" in str(initial_text or ""),
                "final_has_fact_check": "新闻事实核查" in str(final_text or "") or "事实核查" in str(final_text or ""),
                "final_has_error": "总结失败" in str(final_text or ""),
            }
            (OUTPUT_DIR / "page_probe_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            _trace("probe_complete")
    except Exception as exc:
        _trace(f"probe_error={type(exc).__name__}:{exc}")
        raise
    finally:
        _trace("edge_terminate")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            _trace("edge_killed")


if __name__ == "__main__":
    asyncio.run(main())
