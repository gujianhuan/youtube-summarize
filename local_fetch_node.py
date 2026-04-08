import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["LOCAL_FETCH_NODE_MODE"] = "worker"

from core_logic import build_api, format_error, get_transcript_from_input, get_video_transcript


HOST = os.environ.get("LOCAL_FETCH_NODE_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.environ.get("LOCAL_FETCH_NODE_PORT", "8787") or "8787")
TOKEN = os.environ.get("REMOTE_TRANSCRIBE_TOKEN", "").strip()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class FetchHandler(BaseHTTPRequestHandler):
    server_version = "LocalFetchNode/0.1"

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            _json_response(self, 200, {"ok": True, "service": "local-fetch-node"})
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

            video_url = str(payload.get("video_url") or "").strip()
            languages = payload.get("languages") or ["zh-Hans", "zh", "en"]
            if not isinstance(languages, list):
                raise ValueError("languages must be a list")
            languages = [str(item).strip() for item in languages if str(item).strip()]
            if not video_url:
                raise ValueError("video_url is required")

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
            transcript = get_video_transcript(api, video_id, video_url=normalized_url, languages=languages)
            if "\n\n" in transcript:
                label, text = transcript.split("\n\n", 1)
            else:
                label, text = "remote-worker", transcript

            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "transcript_label": label.strip().strip("[]"),
                    "transcript_text": text,
                },
            )
        except Exception as e:
            _json_response(self, 500, {"ok": False, "error": format_error(e)})

    def log_message(self, format, *args):
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), FetchHandler)
    print(f"Local fetch node running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
