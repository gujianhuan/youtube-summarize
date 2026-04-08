import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["LOCAL_FETCH_NODE_MODE"] = "worker"

from core_logic import build_api, format_error, get_transcript_from_input, get_video_transcript


HOST = os.environ.get("LOCAL_FETCH_NODE_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.environ.get("LOCAL_FETCH_NODE_PORT", "8787") or "8787")
TOKEN = os.environ.get("REMOTE_TRANSCRIBE_TOKEN", "").strip()
TASKS: dict[str, dict] = {}
TASKS_LOCK = threading.Lock()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass


def _set_task(task_id: str, **patch) -> None:
    with TASKS_LOCK:
        task = TASKS.get(task_id) or {"task_id": task_id, "status": "queued", "created_at": time.time()}
        task.update(patch)
        TASKS[task_id] = task


def _get_task(task_id: str) -> dict | None:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        return dict(task) if task else None


def _run_fetch_task(task_id: str, payload: dict) -> None:
    try:
        _set_task(task_id, status="running", started_at=time.time())

        video_url = str(payload.get("video_url") or "").strip()
        languages = payload.get("languages") or ["zh-Hans", "zh", "en"]
        if not isinstance(languages, list):
            raise ValueError("languages must be a list")
        languages = [str(item).strip() for item in languages if str(item).strip()]
        if not video_url:
            raise ValueError("video_url is required")
        print(f"[local-fetch-node] received request: url={video_url} langs={','.join(languages)}")

        proxy_url = os.environ.get("PROXY_URL", "").strip()
        timeout_seconds = float(os.environ.get("LOCAL_FETCH_TIMEOUT_SECONDS", "90") or "90")
        retries = int(os.environ.get("LOCAL_FETCH_RETRIES", "1") or "1")
        use_system_proxy = False

        api = build_api(proxy_url, timeout_seconds, use_system_proxy, retries)
        setattr(api, "_cookies_file", str(payload.get("cookies_file") or os.environ.get("YTDLP_COOKIES_FILE", "")).strip())
        setattr(api, "_cookies_content", str(payload.get("cookies_content") or os.environ.get("YTDLP_COOKIES_CONTENT", "")))
        setattr(api, "_cookies_content_b64", str(payload.get("cookies_content_b64") or os.environ.get("YTDLP_COOKIES_CONTENT_B64", "")).strip())
        setattr(api, "_cookies_from_browser", str(payload.get("cookies_from_browser") or os.environ.get("YTDLP_COOKIES_BROWSER", "")).strip().lower())
        setattr(api, "_asr_enabled", bool(payload.get("asr_enabled", True)))
        setattr(api, "_asr_model", str(payload.get("asr_model") or os.environ.get("LOCAL_FETCH_ASR_MODEL", "base")).strip() or "base")
        setattr(api, "_asr_language", str(payload.get("asr_language") or os.environ.get("LOCAL_FETCH_ASR_LANGUAGE", "")).strip())
        setattr(api, "_asr_fast_mode", bool(payload.get("asr_fast_mode", os.environ.get("LOCAL_FETCH_ASR_FAST_MODE", "1").strip() not in {"0", "false", "False"})))
        setattr(api, "_asr_force_cpu", bool(payload.get("asr_force_cpu", os.environ.get("LOCAL_FETCH_ASR_FORCE_CPU", "0").strip() in {"1", "true", "True"})))

        video_id, normalized_url, _ = get_transcript_from_input(video_url, ",".join(languages))
        print(f"[local-fetch-node] normalized video_id={video_id}")
        transcript = get_video_transcript(api, video_id, video_url=normalized_url, languages=languages)
        if "\n\n" in transcript:
            label, text = transcript.split("\n\n", 1)
        else:
            label, text = "remote-worker", transcript
        print(f"[local-fetch-node] success: label={label.strip().strip('[]')} text_len={len(text)}")
        _set_task(
            task_id,
            status="success",
            finished_at=time.time(),
            transcript_label=label.strip().strip("[]"),
            transcript_text=text,
        )
    except Exception as e:
        print(f"[local-fetch-node] failed: {e}")
        _set_task(
            task_id,
            status="failed",
            finished_at=time.time(),
            error=format_error(e),
        )


class FetchHandler(BaseHTTPRequestHandler):
    server_version = "LocalFetchNode/0.1"

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            _json_response(self, 200, {"ok": True, "service": "local-fetch-node"})
            return
        if self.path.startswith("/task/"):
            task_id = self.path.rsplit("/", 1)[-1].strip()
            task = _get_task(task_id)
            if not task:
                _json_response(self, 404, {"ok": False, "error": "task not found"})
                return
            _json_response(self, 200, {"ok": True, **task})
            return
        _json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/fetch-transcript":
            _json_response(self, 404, {"ok": False, "error": "not found"})
            return

        if TOKEN:
            provided = self.headers.get("X-Worker-Token", "").strip()
            if provided != TOKEN:
                _json_response(self, 401, {"ok": False, "error": "invalid worker token"})
                return

        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            task_id = str(uuid.uuid4())
            _set_task(task_id, status="queued")
            worker = threading.Thread(target=_run_fetch_task, args=(task_id, payload), daemon=True)
            worker.start()
            _json_response(self, 202, {"ok": True, "task_id": task_id, "status": "queued"})
        except Exception as e:
            print(f"[local-fetch-node] failed: {e}")
            _json_response(self, 500, {"ok": False, "error": format_error(e)})

    def log_message(self, format, *args):
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), FetchHandler)
    print(f"Local fetch node running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
