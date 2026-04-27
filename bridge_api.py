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
from urllib.parse import parse_qs, quote, urlparse

import requests

BASE_DIR = Path(__file__).resolve().parent
BRIDGE_STORE_FILE = Path(
    os.environ.get("BRIDGE_STORE_FILE", str(BASE_DIR / "bridge_store.json"))
).resolve()
BRIDGE_API_HOST = os.environ.get("BRIDGE_API_HOST", "0.0.0.0")
BRIDGE_API_PORT = int(os.environ.get("PORT", os.environ.get("BRIDGE_API_PORT", "8765")) or "8765")
BRIDGE_TTL_SECONDS = int(os.environ.get("BRIDGE_TTL_SECONDS", "900") or "900")
BRIDGE_MAX_TRANSCRIPT_CHARS = int(
    os.environ.get("BRIDGE_MAX_TRANSCRIPT_CHARS", "250000") or "250000"
)
BRIDGE_API_TOKEN = str(os.environ.get("BRIDGE_API_TOKEN", "") or "").strip()
BRIDGE_STORE_BACKEND = str(os.environ.get("BRIDGE_STORE_BACKEND", "auto") or "auto").strip().lower()
BRIDGE_UPSTASH_FALLBACK_ENABLED = str(
    os.environ.get("BRIDGE_UPSTASH_FALLBACK_ENABLED", "1") or "1"
).strip().lower() not in {"0", "false", "no", "off"}
UPSTASH_REDIS_REST_URL = str(os.environ.get("UPSTASH_REDIS_REST_URL", "") or "").strip().rstrip("/")
UPSTASH_REDIS_REST_TOKEN = str(os.environ.get("UPSTASH_REDIS_REST_TOKEN", "") or "").strip()
STORE_LOCK = threading.Lock()
BRIDGE_SCHEMA_VERSION = "1.0"
BRIDGE_PAYLOAD_VERSION_V1 = 1
BRIDGE_PAYLOAD_VERSION_V2 = 2


def _log(event: str, **kwargs: Any) -> None:
    """输出结构化桥接日志，便于 Render 上排障。"""
    detail = " ".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in kwargs.items())
    if detail:
        print(f"[bridge_api] {event} {detail}")
        return
    print(f"[bridge_api] {event}")


def _is_upstash_configured() -> bool:
    """判断 Upstash Redis REST 连接信息是否完整。"""
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def _get_store_backend() -> str:
    """返回当前实际启用的 bridge 存储后端。"""
    if BRIDGE_STORE_BACKEND == "upstash" and _is_upstash_configured():
        return "upstash"
    if BRIDGE_STORE_BACKEND == "auto" and _is_upstash_configured():
        return "upstash"
    return "local_json"


def _build_payload_key(payload_id: str) -> str:
    """生成稳定的 payload key，避免 Redis 中键名冲突。"""
    return f"bridge:payload:{payload_id}"


def _upstash_request(method: str, command_path: str, *, body: str | None = None) -> dict[str, Any]:
    """调用 Upstash Redis REST API。"""
    if not _is_upstash_configured():
        raise RuntimeError("upstash_not_configured")

    headers = {
        "Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"

    try:
        response = requests.request(
            method=method.upper(),
            url=f"{UPSTASH_REDIS_REST_URL}{command_path}",
            headers=headers,
            data=body.encode("utf-8") if body is not None else None,
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"upstash_request_error:{type(exc).__name__}:{str(exc) or 'unknown'}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        snippet = (response.text or "").strip().replace("\n", " ")[:300]
        raise RuntimeError(
            f"upstash_invalid_json:http_{response.status_code}:{snippet or 'empty_response'}"
        ) from exc

    if response.status_code >= 400 or payload.get("error"):
        raise RuntimeError(str(payload.get("error") or f"upstash_http_{response.status_code}"))
    return payload if isinstance(payload, dict) else {"result": payload}


def _load_payload_from_upstash(payload_id: str) -> dict[str, Any] | None:
    """从 Upstash 读取 payload。"""
    key = quote(_build_payload_key(payload_id), safe="")
    payload = _upstash_request("GET", f"/get/{key}")
    raw_value = payload.get("result")
    if not raw_value:
        return None
    if isinstance(raw_value, dict):
        return raw_value
    try:
        return json.loads(str(raw_value))
    except Exception:
        return None


def _delete_payload_from_upstash(payload_id: str) -> None:
    """从 Upstash 删除 payload。"""
    key = quote(_build_payload_key(payload_id), safe="")
    _upstash_request("GET", f"/del/{key}")


def _save_payload_to_upstash(payload_id: str, payload: dict[str, Any]) -> None:
    """将 payload 写入 Upstash，并依赖 Redis TTL 自动过期。"""
    key = quote(_build_payload_key(payload_id), safe="")
    body = json.dumps(payload, ensure_ascii=False)
    _upstash_request("POST", f"/set/{key}?EX={BRIDGE_TTL_SECONDS}", body=body)


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


def _load_payload_from_local_json(payload_id: str) -> dict[str, Any] | None:
    """从本地 JSON 存储读取 payload。"""
    with STORE_LOCK:
        store = _prune_expired(_load_store())
        payload = store.get(payload_id)
        _save_store(store)
    return payload


def _delete_payload_from_local_json(payload_id: str) -> None:
    """从本地 JSON 存储删除 payload。"""
    with STORE_LOCK:
        store = _prune_expired(_load_store())
        store.pop(payload_id, None)
        _save_store(store)


def _save_payload_to_local_json(payload_id: str, payload: dict[str, Any]) -> None:
    """将 payload 写入本地 JSON 存储。"""
    with STORE_LOCK:
        store = _prune_expired(_load_store())
        store[payload_id] = payload
        _save_store(store)


def _load_payload(payload_id: str) -> dict[str, Any] | None:
    """按当前配置的存储后端读取 payload。"""
    backend = _get_store_backend()
    if backend == "upstash":
        try:
            return _load_payload_from_upstash(payload_id)
        except Exception as exc:
            if not BRIDGE_UPSTASH_FALLBACK_ENABLED:
                raise
            _log(
                "upstash_read_failed_fallback_to_local_json",
                payload_id=payload_id,
                error=f"{type(exc).__name__}:{str(exc) or 'unknown'}",
            )
            return _load_payload_from_local_json(payload_id)

    return _load_payload_from_local_json(payload_id)


def _delete_payload(payload_id: str) -> None:
    """按当前配置的存储后端删除 payload。"""
    backend = _get_store_backend()
    if backend == "upstash":
        try:
            _delete_payload_from_upstash(payload_id)
            return
        except Exception as exc:
            if not BRIDGE_UPSTASH_FALLBACK_ENABLED:
                raise
            _log(
                "upstash_delete_failed_fallback_to_local_json",
                payload_id=payload_id,
                error=f"{type(exc).__name__}:{str(exc) or 'unknown'}",
            )
            _delete_payload_from_local_json(payload_id)
        return

    _delete_payload_from_local_json(payload_id)


def _save_payload(payload_id: str, payload: dict[str, Any]) -> None:
    """按当前配置的存储后端写入 payload。"""
    backend = _get_store_backend()
    if backend == "upstash":
        try:
            _save_payload_to_upstash(payload_id, payload)
            return
        except Exception as exc:
            if not BRIDGE_UPSTASH_FALLBACK_ENABLED:
                raise
            _log(
                "upstash_write_failed_fallback_to_local_json",
                payload_id=payload_id,
                error=f"{type(exc).__name__}:{str(exc) or 'unknown'}",
            )
            _save_payload_to_local_json(payload_id, payload)
        return

    _save_payload_to_local_json(payload_id, payload)


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


def _safe_int(value: Any, default: int) -> int:
    """尽量将值转换成 int，失败时回落到默认值。"""
    try:
        return int(value)
    except Exception:
        return default


def _extract_envelope_text(envelope: dict[str, Any]) -> str:
    """从 Transcript Envelope 中提取 transcript 文本。"""
    transcript = envelope.get("transcript")
    if not isinstance(transcript, dict):
        return ""
    return str(transcript.get("text") or "").strip()


def _normalize_bridge_payload(body: dict[str, Any], *, now_ts: float) -> tuple[str, dict[str, Any]]:
    """兼容 V1/V2 请求体并统一为桥接存储格式。"""

    payload_id = str(body.get("payloadId") or body.get("payload_id") or secrets.token_hex(16)).strip()
    if not payload_id:
        payload_id = secrets.token_hex(16)

    envelope_raw = body.get("envelope")
    envelope = envelope_raw if isinstance(envelope_raw, dict) else None
    bridge_version = _safe_int(
        body.get("bridgeVersion") or body.get("bridge_version") or (BRIDGE_PAYLOAD_VERSION_V2 if envelope else BRIDGE_PAYLOAD_VERSION_V1),
        BRIDGE_PAYLOAD_VERSION_V1,
    )

    transcript = str(body.get("transcript") or "").strip()
    source_url = str(body.get("sourceUrl") or body.get("source_url") or "").strip()
    title = str(body.get("title") or "").strip()
    created_at = str(body.get("createdAt") or body.get("created_at") or "").strip()

    if envelope is not None:
        transcript = transcript or _extract_envelope_text(envelope)
        video = envelope.get("video") if isinstance(envelope.get("video"), dict) else {}
        source_url = source_url or str(video.get("url") or "").strip()
        title = title or str(video.get("title") or "").strip()
        created_at = created_at or str(envelope.get("createdAt") or "").strip()
        if bridge_version < BRIDGE_PAYLOAD_VERSION_V2:
            bridge_version = BRIDGE_PAYLOAD_VERSION_V2

    payload: dict[str, Any] = {
        "payloadId": payload_id,
        "payload_id": payload_id,
        "transcript": transcript,
        "sourceUrl": source_url,
        "source_url": source_url,
        "title": title,
        "createdAt": created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
        "created_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
        "expires_at": now_ts + BRIDGE_TTL_SECONDS,
        "bridgeVersion": bridge_version,
        "bridge_version": bridge_version,
    }

    if envelope is not None:
        payload["schemaVersion"] = str(envelope.get("schemaVersion") or BRIDGE_SCHEMA_VERSION)
        payload["schema_version"] = str(envelope.get("schemaVersion") or BRIDGE_SCHEMA_VERSION)
        payload["envelope"] = envelope

        source = envelope.get("source") if isinstance(envelope.get("source"), dict) else {}
        diagnostics = envelope.get("diagnostics") if isinstance(envelope.get("diagnostics"), dict) else {}
        payload["requestId"] = str(envelope.get("requestId") or "").strip()
        payload["request_id"] = str(envelope.get("requestId") or "").strip()
        payload["sourceKind"] = str(source.get("kind") or "").strip()
        payload["source_kind"] = str(source.get("kind") or "").strip()
        payload["sourceType"] = str(source.get("sourceType") or "").strip()
        payload["source_type"] = str(source.get("sourceType") or "").strip()
        payload["fallbackUsed"] = bool(diagnostics.get("fallbackUsed"))
        payload["fallback_used"] = bool(diagnostics.get("fallbackUsed"))

    return payload_id, payload


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
                    "store_backend": _get_store_backend(),
                    "upstash_configured": _is_upstash_configured(),
                    "upstash_fallback_enabled": BRIDGE_UPSTASH_FALLBACK_ENABLED,
                    "ttl_seconds": BRIDGE_TTL_SECONDS,
                    "max_transcript_chars": BRIDGE_MAX_TRANSCRIPT_CHARS,
                    "supported_bridge_versions": [BRIDGE_PAYLOAD_VERSION_V1, BRIDGE_PAYLOAD_VERSION_V2],
                    "schema_version": BRIDGE_SCHEMA_VERSION,
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

        try:
            payload = _load_payload(payload_id)
            if consume and payload:
                _delete_payload(payload_id)
        except Exception as exc:
            _json_response(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"bridge_read_failed:{type(exc).__name__}:{str(exc) or 'unknown'}"},
            )
            return

        if not payload:
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "payload_not_found"})
            return

        _json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "payload_id": payload_id,
                "bridge_version": _safe_int(payload.get("bridgeVersion"), BRIDGE_PAYLOAD_VERSION_V1),
                "payload": payload,
            },
        )

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

        now_ts = time.time()
        payload_id, payload = _normalize_bridge_payload(body, now_ts=now_ts)
        transcript = str(payload.get("transcript") or "").strip()

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

        try:
            _save_payload(payload_id, payload)
        except Exception as exc:
            _json_response(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"bridge_write_failed:{type(exc).__name__}:{str(exc) or 'unknown'}"},
            )
            return

        _json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "payload_id": payload_id,
                "bridge_version": _safe_int(payload.get("bridgeVersion"), BRIDGE_PAYLOAD_VERSION_V1),
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
