# Render + 本地抓取节点

## 目标

- `Render` 继续负责网页、任务流和 AI 总结
- 本地电脑负责 YouTube 抓取和音频转写
- Render 在抓取失败时，自动转发到本地抓取节点

## Render 端环境变量

- `REMOTE_TRANSCRIBE_URL`
  - 本地抓取节点的完整地址
  - 例如：`https://your-subdomain.example.com/fetch-transcript`
- `REMOTE_TRANSCRIBE_MODE`
  - 可选，设为 `prefer_remote` 时，Render 会优先直接调用本地抓取节点，而不是先自己抓
- `REMOTE_TRANSCRIBE_TOKEN`
  - Render 调本地抓取节点时的认证 token
- `REMOTE_TRANSCRIBE_TIMEOUT_SECONDS`
  - 可选，Render 等待本地抓取节点返回的秒数
  - 建议先设为 `300`
- `REMOTE_TRANSCRIBE_PROCESSING_EXTENSION_SECONDS`
  - 可选，当本地节点已经进入“音频下载 / Whisper 转写”阶段时，Render 额外延长等待秒数
  - 建议先设为 `240`
- `REMOTE_TRANSCRIBE_DISABLE_RENDER_ASR_FALLBACK`
  - 可选，默认 `0`
  - 设为 `1` 时，在 Render 这类低内存环境中，若已配置本地抓取节点，则禁止 Render 自己兜底执行“音频下载 + Whisper 转写”
  - 当前为了先便于测试，默认允许 Render 兜底；如果再次遇到 512MB OOM，再改回 `1`

## 本地抓取节点环境变量

- `REMOTE_TRANSCRIBE_TOKEN`
  - 必填，必须和 Render 端一致
- `LOCAL_FETCH_PREFER_LOCAL_COOKIES`
  - 默认 `1`
  - 本地抓取节点优先使用本机 cookies，而不是 Render 转发过来的 cookies
- `LOCAL_FETCH_SKIP_TRANSCRIPT_API`
  - 默认 `1`
  - 本地抓取节点默认跳过 `youtube_transcript_api`，直接优先尝试 `yt-dlp` 和 Whisper
- `LOCAL_FETCH_COOKIES_BROWSER`
  - 可选，可设为 `auto`、`edge`、`chrome`、`firefox`
  - 推荐优先设为 `auto`
  - 若未设置，在 Windows 下本地节点会自动使用 `auto`，按 `firefox -> edge -> chrome -> brave -> chromium` 回退
- `LOCAL_FETCH_NODE_HOST`
  - 默认 `127.0.0.1`
- `LOCAL_FETCH_NODE_PORT`
  - 默认 `8787`
- `LOCAL_FETCH_ASR_MODEL`
  - 默认 `base`
- `LOCAL_FETCH_ASR_LANGUAGE`
  - 默认空字符串
- `LOCAL_FETCH_ASR_FAST_MODE`
  - 默认 `1`
- `LOCAL_FETCH_ASR_FORCE_CPU`
  - 默认 `0`
- `YTDLP_COOKIES_CONTENT_B64`
  - 可选，和 Render 一样，可在本地抓取节点侧配置 cookies
- `PROXY_URL`
  - 可选，本地抓取节点需要代理时再配

## 本地启动

```bash
python local_fetch_node.py
```

启动后可本地检查：

```bash
curl http://127.0.0.1:8787/health
```

## 暴露给 Render

推荐用 Cloudflare Tunnel、Tailscale Funnel 或 ngrok 暴露本地 `8787` 端口。

注意：

- `trycloudflare.com` 地址是临时的，重启 `cloudflared` 后通常会变化
- 如果要给朋友持续测试，不建议长期使用临时 `trycloudflare` 地址
- 更稳妥的做法是：
  - 使用固定域名的 Cloudflare Tunnel
  - 或使用 Tailscale Funnel / ngrok 固定地址
- 如果 Render 中的 `REMOTE_TRANSCRIBE_URL` 仍指向一个已经失效的临时地址，远程抓取会直接失败

示例：

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

然后把得到的 HTTPS 地址拼成：

```text
https://xxxx.trycloudflare.com/fetch-transcript
```

写入 Render 的 `REMOTE_TRANSCRIBE_URL`。

## 运行逻辑

- Render 先尝试自己的字幕/API/yt-dlp 逻辑
- 当 YouTube 风控导致抓取失败时，Render 会自动调用本地抓取节点
- 本地抓取节点现在是异步任务模式：
  - `POST /fetch-transcript` 提交任务，立即返回 `task_id`
  - `GET /task/<task_id>` 查询任务状态
  - 状态结果里会包含 `stage` 和 `stage_detail`，用于定位卡在抓取、字幕还是转写阶段
- 本地抓取节点任务完成后返回 transcript 文本
- Render 继续调用现有 `summarize_text()` 做总结
