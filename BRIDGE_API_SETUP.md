# Bridge API 部署说明

## 目标

把浏览器扩展提取到的 `transcript` 先提交到一个独立的桥接服务，再由主站按 `payload_id` 拉取，避免继续依赖 DOM 自动填表或页面内 storage。

## 推荐架构

- `Render Web Service`：运行 `bridge_api.py`
- `Upstash Redis`：保存 `payload_id -> payload`
- 现有主站：按 `payload_id` 拉取并自动总结

## 第一步：创建 Upstash Redis

1. 打开 Upstash 控制台。
2. 点击 `Create Database`。
3. 类型选择 `Redis`。
4. 名称随便填，例如：`youtube-summarize-bridge`。
5. Region 选离 Render 更近的区域即可。
6. 创建成功后，进入数据库详情页。
7. 复制这两个值：
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`

## 第二步：在 Render 新建 Bridge API 服务

1. 打开 Render 控制台。
2. 点击 `New +`。
3. 选择 `Web Service`。
4. 代码仓库选择：`gujianhuan/youtube-summarize`
5. Branch 选择：`main`
6. Runtime 选择：`Python 3`
7. Start Command 填：

```bash
python bridge_api.py
```

8. Instance 先用免费或最便宜规格即可。

## 第三步：给 Bridge API 服务配置环境变量

在刚创建的 Bridge API 服务里，进入 `Environment`，新增：

- `BRIDGE_STORE_BACKEND=upstash`
- `BRIDGE_API_HOST=0.0.0.0`
- `BRIDGE_TTL_SECONDS=900`
- `BRIDGE_MAX_TRANSCRIPT_CHARS=250000`
- `BRIDGE_API_TOKEN=`
- `UPSTASH_REDIS_REST_URL=你从 Upstash 复制的 REST URL`
- `UPSTASH_REDIS_REST_TOKEN=你从 Upstash 复制的 REST TOKEN`

说明：

- **不要手动设置 `PORT`**，Render 会自动注入。
- `BRIDGE_API_TOKEN` 现在可以先留空，先把主链路跑通。
- 如果后面要加安全校验，再把主站和扩展一起切到同一个 token。

## 第四步：验证 Bridge API 是否启动成功

Bridge API 部署成功后，访问：

```http
GET https://你的-bridge-服务.onrender.com/health
```

预期至少看到类似字段：

```json
{
  "ok": true,
  "service": "transcript-bridge",
  "store_backend": "upstash",
  "upstash_configured": true
}
```

如果这里看到：

- `store_backend = local_json`
- 或 `upstash_configured = false`

说明你的 Upstash 环境变量没配对。

## 第五步：给主站配置 Bridge API 地址

进入你现有主站的 Render 服务，在 `Environment` 中新增：

- `BRIDGE_API_URL=https://你的-bridge-服务.onrender.com`
- `BRIDGE_API_TOKEN=`

然后重新部署主站。

## 第六步：刷新浏览器扩展

当前扩展版本已切到服务端桥接流。

操作：

1. 打开 `chrome://extensions/`
2. 找到 `Video Transcript Helper MVP`
3. 点一次 `刷新`
4. 确认版本已更新到最新打包版本

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

- 当前 `bridge_api.py` 已支持 `Upstash Redis`，并保留本地 JSON 回退。
- 如果 Upstash 环境变量漏配，服务仍可能回退到 `local_json`，这适合排障，但不适合你现在的线上桥接目标。
- 真正商业化阶段建议补充：
  - token 校验
  - 访问限流
  - 失败重试
  - 更细的审计日志
