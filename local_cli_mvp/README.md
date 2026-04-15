# 本地 CLI / 小助手 MVP

这是“第二兜底”方案的最小可用版本：

- 输入 YouTube / Bilibili 链接
- 在本机优先尝试字幕
- 抓不到时走本机 `yt-dlp + Whisper`
- 输出 transcript 文件
- 可选直接调用现有大模型配置输出总结

## 为什么需要它

当浏览器扩展拿不到 transcript，或者页面没有可见字幕时，本地 CLI 可以继续尝试“最低音频/最低质量流 + 本地转写”。

这条链路运行在用户自己的电脑上，更适合：

- 使用本机浏览器 cookies
- 使用本机网络/IP
- 使用本机 CPU/GPU 做 Whisper

## 快速开始

```powershell
Set-Location "D:\Program Files\Trae\YouTubeSummarizer"
python .\local_cli_mvp\video_local_helper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
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

## 输出

默认输出到 `local_cli_mvp_output` 目录：

- `*.transcript.txt`
- `*.summary.json`（如果启用了 `--summary`）

## 说明

- 这个 MVP 会强制本地优先，不走 Render 远程抓取节点
- `--cookies-browser auto` 适合你当前项目的思路
- 如果本机有 GPU，会由现有 core logic 决定是否使用 GPU Whisper

## 下一步可增强

- 直接把 transcript 自动推送到主站 `✍️ 粘贴字幕`
- 做成桌面 GUI 小助手
- 支持批量任务与历史记录
