"""在线安装版运行时下载器的轻量测试。"""

import json
from pathlib import Path

from local_cli_mvp.online_runtime_installer import (
    DEFAULT_RUNTIME_MANIFEST,
    MANIFEST_FILE_NAME,
    ensure_runtime_dirs,
    get_runtime_dirs,
    load_runtime_manifest,
)


def test_get_runtime_dirs_contains_expected_keys() -> None:
    """应返回在线安装版使用的关键目录。"""

    runtime_dirs = get_runtime_dirs()

    assert "runtime" in runtime_dirs
    assert "downloads" in runtime_dirs
    assert "logs" in runtime_dirs


def test_ensure_runtime_dirs_creates_directories() -> None:
    """应创建在线安装版所需目录。"""

    runtime_dirs = ensure_runtime_dirs()

    assert runtime_dirs["runtime"].exists()
    assert runtime_dirs["downloads"].exists()
    assert runtime_dirs["logs"].exists()


def test_load_runtime_manifest_uses_defaults_when_env_missing() -> None:
    """未配置环境变量时应返回默认清单结构。"""

    manifest = load_runtime_manifest()

    assert manifest.version
    assert manifest.executable_name == DEFAULT_RUNTIME_MANIFEST.executable_name


def test_load_runtime_manifest_from_file() -> None:
    """存在清单文件时应优先读取文件配置。"""

    module_dir = Path(__file__).resolve().parents[1] / "local_cli_mvp"
    manifest_path = module_dir / MANIFEST_FILE_NAME
    original_content = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
    manifest_path.write_text(
        json.dumps(
            {
                "version": "test-version",
                "package_url": "https://example.com/runtime.zip",
                "package_sha256": "abc",
                "executable_name": "Demo.exe",
            }
        ),
        encoding="utf-8",
    )
    try:
        manifest = load_runtime_manifest()
        assert manifest.version == "test-version"
        assert manifest.package_url == "https://example.com/runtime.zip"
        assert manifest.executable_name == "Demo.exe"
    finally:
        if original_content is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_text(original_content, encoding="utf-8")
