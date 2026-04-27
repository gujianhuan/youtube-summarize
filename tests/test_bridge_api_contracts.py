"""Bridge API contract compatibility tests."""

from bridge_api import (
    BRIDGE_PAYLOAD_VERSION_V1,
    BRIDGE_PAYLOAD_VERSION_V2,
    _normalize_bridge_payload,
)


def test_normalize_bridge_payload_v1_shape() -> None:
    """V1 payload should remain accepted and normalized."""

    payload_id, payload = _normalize_bridge_payload(
        {
            "payloadId": "payload-v1",
            "transcript": "hello world",
            "sourceUrl": "https://www.youtube.com/watch?v=demo",
            "title": "Demo",
            "bridgeVersion": 1,
        },
        now_ts=1_700_000_000,
    )

    assert payload_id == "payload-v1"
    assert payload["transcript"] == "hello world"
    assert payload["sourceUrl"] == "https://www.youtube.com/watch?v=demo"
    assert payload["bridgeVersion"] == BRIDGE_PAYLOAD_VERSION_V1


def test_normalize_bridge_payload_v2_shape() -> None:
    """V2 payload should flatten useful fields while preserving envelope."""

    payload_id, payload = _normalize_bridge_payload(
        {
            "payloadId": "payload-v2",
            "bridgeVersion": 2,
            "envelope": {
                "schemaVersion": "1.0",
                "requestId": "req-123",
                "source": {
                    "kind": "local_tool",
                    "sourceType": "local_asr",
                    "toolVersion": "local-helper-0.1.0",
                },
                "video": {
                    "platform": "youtube",
                    "videoId": "demo",
                    "url": "https://www.youtube.com/watch?v=demo",
                    "title": "Demo Title",
                },
                "transcript": {
                    "text": "transcribed text",
                    "segments": [],
                    "charCount": 15,
                },
                "diagnostics": {
                    "textSourceReason": "no_text_source_found",
                    "fallbackUsed": True,
                },
                "createdAt": "2026-04-23T15:00:00Z",
            },
        },
        now_ts=1_700_000_000,
    )

    assert payload_id == "payload-v2"
    assert payload["bridgeVersion"] == BRIDGE_PAYLOAD_VERSION_V2
    assert payload["transcript"] == "transcribed text"
    assert payload["sourceUrl"] == "https://www.youtube.com/watch?v=demo"
    assert payload["title"] == "Demo Title"
    assert payload["requestId"] == "req-123"
    assert payload["sourceKind"] == "local_tool"
    assert payload["fallbackUsed"] is True
    assert isinstance(payload["envelope"], dict)


def test_normalize_bridge_payload_promotes_envelope_version() -> None:
    """Envelope input should be promoted to V2 even if version is omitted."""

    _, payload = _normalize_bridge_payload(
        {
            "payloadId": "payload-auto-v2",
            "envelope": {
                "schemaVersion": "1.0",
                "requestId": "req-456",
                "source": {
                    "kind": "extension",
                    "sourceType": "subtitle",
                    "toolVersion": "extension-0.1.0",
                },
                "video": {
                    "platform": "youtube",
                    "videoId": "demo",
                    "url": "https://www.youtube.com/watch?v=demo",
                },
                "transcript": {
                    "text": "subtitle text",
                    "segments": [],
                    "charCount": 13,
                },
                "diagnostics": {
                    "textSourceReason": "subtitle_panel_available",
                    "fallbackUsed": False,
                },
            },
        },
        now_ts=1_700_000_000,
    )

    assert payload["bridgeVersion"] == BRIDGE_PAYLOAD_VERSION_V2
