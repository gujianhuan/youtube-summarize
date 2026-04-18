# Bridge API 部署说明

## 目标

把浏览器扩展提取到的 `transcript` 先提交到一个独立的桥接服务，再由主站按 `payload_id` 拉取，避免继续依赖 DOM 自动填表或页面内 storage。

## 新增服务

在 Render 新建一个 **Web Service**，代码仓库仍指向当前仓库：

- Repo: `gujianhuan/youtube-summarize`
- Branch: `main`
- Start Command:

```bash
python bridge_api.py
```

## 推荐环境变量

- `BRIDGE_API_HOST=0.0.0.0`
- `BRIDGE_API_PORT=8765`
- `BRIDGE_TTL_SECONDS=900`
- `BRIDGE_MAX_TRANSCRIPT_CHARS=250000`
- `BRIDGE_API_TOKEN=`

说明：

- `BRIDGE_API_TOKEN` 可选。若填写，主站和扩展都要同步同一个 token。
- 当前扩展代码默认未携带 token，因此如要先快速跑通，建议先留空。

## 主站环境变量

在现有主站 Render 服务增加：

- `BRIDGE_API_URL=https://你的-bridge-服务.onrender.com`
- `BRIDGE_API_TOKEN=`

## 当前接口

### 健康检查

```http
GET /health
```

### 提交 payload

```http
POST /api/bridge/payload
Content-Type: application/json

{
  "payloadId": "uuid",
  "transcript": "字幕正文",
  "sourceUrl": "https://www.youtube.com/watch?v=...",
  "title": "视频标题",
  "createdAt": "2026-04-18T12:00:00Z",
  "bridgeVersion": 1
}
```

### 拉取 payload

```http
GET /api/bridge/payload?payload_id=uuid&consume=1
```

## 风险点

- 当前 bridge API 默认使用本地 JSON 文件持久化，适合 MVP/低并发验证，不适合高并发生产。
- 如果 Render 服务重启，未消费的 payload 仍可保留，但不适合长期堆积。
- 真正商业化阶段建议迁移到 Redis / PostgreSQL。
