# 本地 CLI / 小助手 MVP

这是“第二兜底”方案的最小可用版本：

- 输入 YouTube / Bilibili 链接
- 在本机优先尝试字幕
- 抓不到时走本机 `yt-dlp + Whisper`
- 输出 transcript 文件
- 可选自动上传到主站 bridge 并打开主站自动总结
- 可选直接调用现有大模型配置输出总结
- 提供一个可双击打开的简单 GUI 小助手

## 为什么需要它

当浏览器扩展拿不到 transcript，或者页面没有可见字幕时，本地 CLI 可以继续尝试“最低音频/最低质量流 + 本地转写”。

这条链路运行在用户自己的电脑上，更适合：

- 使用本机浏览器 cookies
- 使用本机网络/IP
- 使用本机 CPU/GPU 做 Whisper

## 快速开始

### 方式 1：双击打开 GUI 小助手

在 Windows 下，先完成 Python 环境和依赖安装，然后直接双击：

- `local_cli_mvp\打开本地转写助手.cmd`
- 或更稳一些，直接双击：`local_cli_mvp\打开本地转写助手.vbs`

打开后可在界面中：

- 输入视频链接
- 选择是否上传到主站
- 点击“开始转写”

说明：

- `.vbs` 是当前更稳的双击入口，不经过 `cmd` 的复杂参数解析
- `.cmd` 现在只是一个很薄的包装层，会转调 `.vbs`
- 如果 GUI 启动失败，会弹出错误框，而不是静默没有反应

### 方式 2：命令行运行

```powershell
Set-Location "D:\Program Files\Trae\YouTubeSummarizer"
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

如果你要走 1C 最小闭环，建议直接使用：

```powershell
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --cookies-browser auto --push-to-main
```

## 常用示例

使用浏览器 cookies，本地转写并输出 transcript：

```powershell
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --cookies-browser auto
```

本地转写后顺手生成总结：

```powershell
$env:OPENAI_API_KEY="你的Key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
python .\local_cli_mvp\video_local_helper.py "https://www.bilibili.com/video/BV1xx411c7mD" --cookies-browser auto --summary
```

本地转写完成后，自动上传 transcript 到主站并打开浏览器：

```powershell
$env:MAIN_APP_URL="https://youtube-summarize-0oms.onrender.com/"
$env:BRIDGE_API_URL="https://youtube-summarize-bridge.onrender.com"
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --cookies-browser auto --push-to-main
```

如果只想上传 bridge，但不想自动打开浏览器：

```powershell
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --cookies-browser auto --push-to-main --no-open-browser
```

## 输出

默认输出到 `local_cli_mvp_output` 目录：

- `*.transcript.txt`
- `*.summary.json`（如果启用了 `--summary`）

如果启用了 `--push-to-main`，终端还会输出：

- `bridge_payload_id`
- `main_url`

## 说明

- 这个 MVP 会强制本地优先，不走 Render 远程抓取节点
- `--cookies-browser auto` 适合你当前项目的思路
- 如果本机有 GPU，会由现有 core logic 决定是否使用 GPU Whisper
- GUI 基于 Python 自带 `tkinter`，当前阶段不需要额外桌面框架
- `--push-to-main` 会走现有 bridge 链路，把 transcript 送到主站 `✍️ 粘贴字幕` 页，并带 `ext_autosubmit=1`
- 默认主站地址可通过 `MAIN_APP_URL` 覆盖，默认 bridge 地址可通过 `BRIDGE_API_URL` 覆盖
- 如果 bridge 开启了 token 校验，可通过 `BRIDGE_API_TOKEN` 或 `--bridge-api-token` 传入
- 双击启动前请确认系统里能找到 `pythonw` 或 `pyw`

## Windows 便携版打包

如果你要把它发给“只会双击、不想装 Python”的普通用户，推荐构建
Windows 便携版目录。

### 目标形态

- 一个可直接分发的目录，而不是单文件黑盒 exe
- 用户解压后双击 `LocalTranscriptHelper.exe`
- 目录内同时包含 Python 运行时、依赖、`ffmpeg`、Whisper 模型和日志目录

### 构建命令

在 Windows PowerShell 下执行：

```powershell
Set-Location "D:\Program Files\Trae\YouTubeSummarizer"
python .\local_cli_mvp\build_windows_portable.py
```

构建完成后，默认输出到：

- `dist\LocalTranscriptHelper`

### 发布目录说明

- `LocalTranscriptHelper.exe`：普通用户双击入口
- `models\`：内置 faster-whisper 模型
- `ffmpeg\ffmpeg.exe`：内置 ffmpeg
- `local_cli_mvp_output\`：默认输出目录
- `logs\`：启动和运行日志
- `使用说明.txt`：给测试用户的简明说明

### 风险点

- `bridge` 上传依赖网络和远程服务，可能出现“本地转写成功但上传失败”
- `PyInstaller` 产物在少数 Windows 机器上可能被杀软误报
- 如果模型目录不完整，便携版虽然能启动，但转写阶段会失败

## 下一步可增强

- 支持批量任务与历史记录
- 做成主站触发本地 CLI 的 1A 方案
- 后续再打包成 `.exe`，减少 Python 环境依赖
