# Render + 本地抓取节点

## 目标

- `Render` 继续负责网页、任务流和 AI 总结
- 本地电脑负责 YouTube 抓取和音频转写
- Render 在抓取失败时，自动转发到本地抓取节点

## Render 端环境变量

- `REMOTE_TRANSCRIBE_URL`
  - 本地抓取节点的完整地址
  - 例如：`https://your-subdomain.example.com/fetch-transcript`
- `REMOTE_TRANSCRIBE_TOKEN`
  - Render 调本地抓取节点时的认证 token

## 本地抓取节点环境变量

- `REMOTE_TRANSCRIBE_TOKEN`
  - 必填，必须和 Render 端一致
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
- 本地抓取节点返回 transcript 文本
- Render 继续调用现有 `summarize_text()` 做总结
