"""
构建 Windows 便携版目录。

输出形态：
- onedir GUI exe
- 自带 ffmpeg
- 自带 Whisper 模型目录
- 自带输出目录、日志目录和简明使用说明
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "LocalTranscriptHelper"


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
    spec_file = local_cli_dir / "windows_portable.spec"
    dist_dir = dist_root / APP_NAME
    return {
        "local_cli_dir": local_cli_dir,
        "project_root": project_root,
        "build_dir": build_dir,
        "dist_root": dist_root,
        "dist_dir": dist_dir,
        "spec_file": spec_file,
        "models_dir": local_cli_dir / "models",
    }


def ensure_build_requirements() -> None:
    """检查构建依赖是否齐全。"""

    if os.name != "nt":
        raise RuntimeError("当前脚本仅支持在 Windows 上构建便携版。")

    try:
        import PyInstaller  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "未检测到可用的 PyInstaller。请先执行 `python -m pip install pyinstaller`。"
        ) from exc

    try:
        import imageio_ffmpeg  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "未检测到 imageio-ffmpeg，无法打包 ffmpeg。请先安装项目依赖。"
        ) from exc


def resolve_ffmpeg_binary() -> Path:
    """定位本机可用于分发的 ffmpeg 可执行文件。"""

    import imageio_ffmpeg

    ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    if not ffmpeg_path.exists():
        raise RuntimeError(f"未找到 ffmpeg 可执行文件：{ffmpeg_path}")
    return ffmpeg_path


def ensure_models_dir(models_dir: Path) -> None:
    """确认本地 Whisper 模型目录存在。"""

    if not models_dir.exists():
        raise RuntimeError(
            f"未找到模型目录：{models_dir}\n请先在开发环境运行一次本地转写，确保模型已下载完成。"
        )

    model_bin_files = list(models_dir.rglob("model.bin"))
    if not model_bin_files:
        raise RuntimeError(
            f"模型目录存在但未发现 model.bin：{models_dir}\n请确认 faster-whisper 模型已完整下载。"
        )


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


def copy_tree(src: Path, dst: Path) -> None:
    """复制目录，已存在时覆盖目标内容。"""

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def write_usage_file(dist_dir: Path) -> None:
    """写入普通用户可读的使用说明。"""

    usage_file = dist_dir / "使用说明.txt"
    usage_file.write_text(
        "\n".join(
            [
                "本地转写助手 - Windows 便携版",
                "",
                "使用方法：",
                "1. 解压整个目录，不要只拷贝 exe 单文件。",
                "2. 双击 LocalTranscriptHelper.exe。",
                "3. 输入视频链接后点击“开始转写”。",
                "",
                "目录说明：",
                "- models: 内置 Whisper 模型，请勿删除。",
                "- ffmpeg: 内置音频处理工具，请勿删除。",
                "- local_cli_mvp_output: transcript 默认输出目录。",
                "- logs: 启动和运行日志。",
                "",
                "风险提示：",
                "- 首次运行如果被杀毒软件拦截，请手动放行。",
                "- 上传主站功能依赖网络和远程 bridge 服务，可本地转写成功但上传失败。",
                "",
                "排障建议：",
                "- 如启动失败，请把 logs 目录里的日志发给开发者。",
            ]
        ),
        encoding="utf-8",
    )


def stage_portable_assets(layout: dict[str, Path], ffmpeg_binary: Path) -> None:
    """复制模型、ffmpeg 与辅助目录到发布目录。"""

    dist_dir = layout["dist_dir"]
    if not dist_dir.exists():
        raise RuntimeError(f"未找到 PyInstaller 输出目录：{dist_dir}")

    models_target = dist_dir / "models"
    ffmpeg_target_dir = dist_dir / "ffmpeg"
    output_dir = dist_dir / "local_cli_mvp_output"
    logs_dir = dist_dir / "logs"

    logging.info("复制模型目录到发布目录")
    copy_tree(layout["models_dir"], models_target)

    logging.info("复制 ffmpeg 到发布目录")
    ffmpeg_target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ffmpeg_binary, ffmpeg_target_dir / "ffmpeg.exe")

    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    write_usage_file(dist_dir)


def main() -> int:
    """构建入口。"""

    configure_logging()
    layout = get_project_layout()
    logging.info("构建目录：%s", layout["dist_dir"])

    ensure_build_requirements()
    ensure_models_dir(layout["models_dir"])
    ffmpeg_binary = resolve_ffmpeg_binary()

    run_pyinstaller(layout)
    stage_portable_assets(layout, ffmpeg_binary)

    logging.info("Windows 便携版构建完成：%s", layout["dist_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
