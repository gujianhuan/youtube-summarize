"""
构建 Windows 在线安装版目录。

输出形态：
- onedir GUI exe
- 首包只保留启动器
- 首次运行自动下载完整瘦身运行包
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from online_runtime_installer import load_runtime_manifest


APP_NAME = "LocalTranscriptHelperOnline"


def configure_logging() -> None:
    """初始化构建日志。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def get_project_layout() -> dict[str, Path]:
    """解析项目目录结构。"""

    local_cli_dir = Path(__file__).resolve().parent
    project_root = local_cli_dir.parent
    build_dir = project_root / "build"
    dist_root = project_root / "dist"
    spec_file = local_cli_dir / "windows_online.spec"
    dist_dir = dist_root / APP_NAME
    return {
        "local_cli_dir": local_cli_dir,
        "project_root": project_root,
        "build_dir": build_dir,
        "dist_root": dist_root,
        "dist_dir": dist_dir,
        "spec_file": spec_file,
    }


def ensure_build_requirements() -> None:
    """检查构建依赖是否齐全。"""

    if os.name != "nt":
        raise RuntimeError("当前脚本仅支持在 Windows 上构建在线安装版。")

    try:
        import PyInstaller  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "未检测到可用的 PyInstaller。请先执行 `python -m pip install pyinstaller`。"
        ) from exc


def run_pyinstaller(layout: dict[str, Path]) -> None:
    """执行 PyInstaller 构建。"""

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(layout["spec_file"]),
        "--noconfirm",
        "--clean",
    ]
    logging.info("开始执行 PyInstaller: %s", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=layout["project_root"],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PyInstaller 构建失败，退出码：{completed.returncode}")


def write_usage_file(dist_dir: Path) -> None:
    """写入普通用户可读的使用说明。"""

    usage_file = dist_dir / "使用说明.txt"
    usage_file.write_text(
        "\n".join(
            [
                "本地转写助手 - Windows 在线安装版",
                "",
                "使用方法：",
                "1. 解压整个目录，不要只拷贝 exe 单文件。",
                "2. 双击 LocalTranscriptHelperOnline.exe。",
                "3. 首次运行会自动下载完整运行包，请保持联网。",
                "4. 下载完成后会自动启动真正的本地转写助手。",
                "",
                "重要说明：",
                "- 这个在线安装版本质是一个小启动器。",
                "- 首包体积更小，但首次运行必须联网。",
                "- 运行包默认下载到用户目录，不写入当前解压目录。",
                "- 资源目录通常位于 %LOCALAPPDATA%\\LocalTranscriptHelper。",
                "",
                "风险提示：",
                "- 若网络不可用，首次运行无法完成安装。",
                "- 若 `online_runtime_manifest.json` 里的 package_url 未配置，在线安装版不会自动成功。",
                "- 上传主站功能依赖网络和远程 bridge 服务，可本地转写成功但上传失败。",
                "",
                "排障建议：",
                "- 如启动失败，请把 %LOCALAPPDATA%\\LocalTranscriptHelper\\logs 目录里的日志发给开发者。",
            ]
        ),
        encoding="utf-8",
    )


def write_runtime_manifest(dist_dir: Path) -> None:
    """将已解析的在线安装清单写入分发目录根部。"""

    manifest = load_runtime_manifest()
    if not manifest.package_url:
        raise RuntimeError(
            "在线安装版缺少 package_url。请先配置 "
            "`local_cli_mvp/online_runtime_manifest.json`，或在构建前设置 "
            "`LOCAL_HELPER_ONLINE_PACKAGE_URL`。"
        )

    manifest_path = dist_dir / "online_runtime_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": manifest.version,
                "package_url": manifest.package_url,
                "package_sha256": manifest.package_sha256,
                "executable_name": manifest.executable_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def stage_online_assets(layout: dict[str, Path]) -> None:
    """补充在线安装版分发目录。"""

    dist_dir = layout["dist_dir"]
    if not dist_dir.exists():
        raise RuntimeError(f"未找到 PyInstaller 输出目录：{dist_dir}")

    write_runtime_manifest(dist_dir)
    write_usage_file(dist_dir)


def build_zip(layout: dict[str, Path]) -> Path:
    """压缩在线安装版目录，便于直接分发。"""

    zip_path = layout["dist_root"] / f"{APP_NAME}-win-x64.zip"
    if zip_path.exists():
        zip_path.unlink()

    shutil.make_archive(
        base_name=str(zip_path.with_suffix("")),
        format="zip",
        root_dir=str(layout["dist_dir"]),
    )
    return zip_path


def main() -> int:
    """构建入口。"""

    configure_logging()
    layout = get_project_layout()
    logging.info("构建目录：%s", layout["dist_dir"])

    ensure_build_requirements()
    run_pyinstaller(layout)
    stage_online_assets(layout)
    zip_path = build_zip(layout)

    logging.info("Windows 在线安装版构建完成：%s", layout["dist_dir"])
    logging.info("压缩包路径：%s", zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
