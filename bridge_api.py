"""轻量 transcript bridge API。

职责：
1. 供浏览器扩展提交 transcript/sourceUrl/title；
2. 供主站按 payload_id 拉取一次性载荷；
3. 尽量保持零额外基础设施依赖，默认使用本地 JSON 文件持久化。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
BRIDGE_STORE_FILE = Path(
    os.environ.get("BRIDGE_STORE_FILE", str(BASE_DIR / "bridge_store.json"))
).resolve()
BRIDGE_API_HOST = os.environ.get("BRIDGE_API_HOST", "0.0.0.0")
BRIDGE_API_PORT = int(os.environ.get("BRIDGE_API_PORT", "8765") or "8765")
BRIDGE_TTL_SECONDS = int(os.environ.get("BRIDGE_TTL_SECONDS", "900") or "900")
BRIDGE_MAX_TRANSCRIPT_CHARS = int(
    os.environ.get("BRIDGE_MAX_TRANSCRIPT_CHARS", "250000") or "250000"
)
BRIDGE_API_TOKEN = str(os.environ.get("BRIDGE_API_TOKEN", "") or "").strip()
STORE_LOCK = threading.Lock()


def _load_store() -> dict[str, dict[str, Any]]:
    """读取 bridge 存储文件。"""
    if not BRIDGE_STORE_FILE.exists():
        return {}
    try:
        return json.loads(BRIDGE_STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_store(data: dict[str, dict[str, Any]]) -> None:
    """安全写回 bridge 存储文件。"""
    BRIDGE_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIDGE_STORE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prune_expired(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """删除超时 payload，避免 JSON 文件无限膨胀。"""
    now_ts = time.time()
    result: dict[str, dict[str, Any]] = {}
    for payload_id, payload in data.items():
        expires_at = float(payload.get("expires_at") or 0)
        if expires_at > now_ts:
            result[payload_id] = payload
    return result


def _require_token(headers) -> str | None:
    """校验桥接 token，未配置时允许匿名访问。"""
    if not BRIDGE_API_TOKEN:
        return None
    header_token = str(headers.get("X-Bridge-Token", "") or "").strip()
    if not header_token or not secrets.compare_digest(header_token, BRIDGE_API_TOKEN):
        return "bridge_token_invalid"
    return None


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    """返回 JSON 响应。"""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(encoded)


class BridgeHandler(BaseHTTPRequestHandler):
    """处理扩展提交和主站拉取请求。"""

    server_version = "TranscriptBridge/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        _json_response(self, HTTPStatus.OK, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "transcript-bridge",
                    "ttl_seconds": BRIDGE_TTL_SECONDS,
                    "max_transcript_chars": BRIDGE_MAX_TRANSCRIPT_CHARS,
                },
            )
            return

        if parsed.path != "/api/bridge/payload":
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        token_error = _require_token(self.headers)
        if token_error:
            _json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": token_error})
            return

        params = parse_qs(parsed.query)
        payload_id = str((params.get("payload_id") or [""])[0] or "").strip()
        consume = str((params.get("consume") or ["1"])[0] or "1").strip().lower() in {"1", "true", "yes"}
        if not payload_id:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "payload_id_required"})
            return

        with STORE_LOCK:
            store = _prune_expired(_load_store())
            payload = store.get(payload_id)
            if consume and payload:
                store.pop(payload_id, None)
            _save_store(store)

        if not payload:
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "payload_not_found"})
            return

        _json_response(self, HTTPStatus.OK, {"ok": True, "payload": payload})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/bridge/payload":
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        token_error = _require_token(self.headers)
        if token_error:
            _json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": token_error})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            content_length = 0
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        transcript = str(body.get("transcript") or "").strip()
        source_url = str(body.get("sourceUrl") or "").strip()
        title = str(body.get("title") or "").strip()
        payload_id = str(body.get("payloadId") or secrets.token_hex(16)).strip()

        if not transcript:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "transcript_required"})
            return
        if len(transcript) > BRIDGE_MAX_TRANSCRIPT_CHARS:
            _json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "transcript_too_large", "max_chars": BRIDGE_MAX_TRANSCRIPT_CHARS},
            )
            return

        now_ts = time.time()
        payload = {
            "payloadId": payload_id,
            "transcript": transcript,
            "sourceUrl": source_url,
            "title": title,
            "createdAt": body.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
            "expires_at": now_ts + BRIDGE_TTL_SECONDS,
            "bridgeVersion": int(body.get("bridgeVersion") or 1),
        }

        with STORE_LOCK:
            store = _prune_expired(_load_store())
            store[payload_id] = payload
            _save_store(store)

        _json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "payload_id": payload_id,
                "expires_in": BRIDGE_TTL_SECONDS,
            },
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        """输出简洁日志，便于 Render/本地调试。"""
        print(f"[bridge_api] {self.address_string()} - {format % args}")


def run_bridge_api() -> None:
    """启动独立 bridge API 服务。"""
    server = ThreadingHTTPServer((BRIDGE_API_HOST, BRIDGE_API_PORT), BridgeHandler)
    print(
        f"Transcript bridge API running at http://{BRIDGE_API_HOST}:{BRIDGE_API_PORT} "
        f"(ttl={BRIDGE_TTL_SECONDS}s, max_chars={BRIDGE_MAX_TRANSCRIPT_CHARS})"
    )
    server.serve_forever()


if __name__ == "__main__":
    run_bridge_api()
