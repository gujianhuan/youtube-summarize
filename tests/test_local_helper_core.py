"""`local_helper_core` 的轻量单元测试。"""

from local_cli_mvp.local_helper_core import (
    BRIDGE_PAYLOAD_VERSION,
    TRANSCRIPT_SCHEMA_VERSION,
    build_local_transcript_envelope,
    build_main_url,
    format_local_helper_error,
    safe_name,
)


def test_safe_name_replaces_unsafe_chars() -> None:
    """应将不安全字符替换为下划线。"""

    assert safe_name("a/b:c*demo") == "a_b_c_demo"


def test_build_main_url_appends_required_query() -> None:
    """应生成带 bridge 参数的主站 URL。"""

    result = build_main_url("https://example.com/app", "payload123", "https://video.test/watch?v=1")

    assert "ext_payload_id=payload123" in result
    assert "ext_autosubmit=1" in result
    assert "ext_source_url=" in result


def test_format_local_helper_error_for_bridge_message() -> None:
    """应将 bridge 错误转换成更易懂的提示。"""

    result = format_local_helper_error(RuntimeError("bridge_upload_failed:http_500"))

    assert result.startswith("主站上传失败：")


def test_build_local_transcript_envelope_contains_expected_fields() -> None:
    """本地工具应构造标准 envelope 结构。"""

    envelope = build_local_transcript_envelope(
        request_id="req-1",
        transcript="hello world",
        source_url="https://www.youtube.com/watch?v=demo",
        title="Demo",
        video_id="demo",
        language="en",
    )

    assert envelope["schemaVersion"] == TRANSCRIPT_SCHEMA_VERSION
    assert envelope["requestId"] == "req-1"
    assert envelope["source"]["kind"] == "local_tool"
    assert envelope["source"]["sourceType"] == "local_asr"
    assert envelope["video"]["videoId"] == "demo"
    assert envelope["transcript"]["text"] == "hello world"
    assert envelope["transcript"]["charCount"] == len("hello world")
    assert envelope["diagnostics"]["fallbackUsed"] is True


def test_bridge_payload_version_is_v2_for_local_helper() -> None:
    """本地工具桥接上传应默认使用 V2。"""

    assert BRIDGE_PAYLOAD_VERSION == 2
