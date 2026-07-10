# YouTubeSummarizer / ClipBrief AI 项目交接文档

更新时间：2026-07-10  
当前主分支最新提交：`8d84ae93 Switch default models to NVIDIA NIM DeepSeek`

## 1. 给下一个 Codex 的第一句话

先读本文件，再读：

- `PROJECT_HANDOFF_2026-05-30.md`
- `AI_SESSION_HANDOFF_PROMPT.md`
- `NOTEGPT_BENCHMARK_TECH_PLAN.md`
- `BRIDGE_API_SETUP.md`
- `chrome_extension_mvp/RELEASE_GUIDE.md`
- `chrome_extension_mvp/CHROME_WEB_STORE_CHECKLIST.md`

旧文档可能过时，本文件以 2026-07-10 当前状态为准。不要把 API key、Upstash token、NVIDIA NIM token 写进代码、文档或 Git。

## 2. 项目当前定位

产品名：`ClipBrief AI`

核心目标：

- Chrome 扩展在当前 YouTube 页面内提取 transcript。
- 扩展把 transcript 上传到 bridge。
- 主站读取 bridge payload，生成总结和新闻/事实核查。
- 普通用户主要使用线上主站，不依赖本地转写。

当前主链路是 `extension-first`：

1. 用户打开 YouTube 视频页。
2. 点击 Chrome 扩展。
3. 扩展优先在当前页读取字幕轨道、页面内数据、transcript 面板。
4. 扩展上传 transcript 到 bridge。
5. 主站打开总结页并消费 bridge payload。
6. 主站调用大模型生成总结和核查。

不要把 Render 服务端抓 YouTube transcript 作为普通用户主链路。Render/云服务 IP 容易被 YouTube 429，用户浏览器内提取才是主方向。

## 3. 仓库和分支

本地路径：

```powershell
D:\Workspace\YouTubeSummarizer
```

Git remote：

```text
origin   git@github-ytsum:gujianhuan/youtube-summarize.git
upstream git@github-ytsum:gujianhuan/youtube-summarize.git
```

默认工作分支：`main`

最近关键提交：

```text
8d84ae93 Switch default models to NVIDIA NIM DeepSeek
48d7b2e9 Polish guestbook layout and model settings
e449e85f Show guestbook replies and add likes
683c135a Store guestbook in Upstash when configured
a220e98b Persist mutable JSON data under DATA_DIR
1b4123dd Shorten bilingual store summary
d8e232a6 Add bilingual Chrome Web Store copy
7d20ad07 Prepare ClipBrief AI Chrome release
```

当前工作区有很多历史调试文件、浏览器 profile、临时输出。不要随手 `git add .`。提交时只 stage 本次明确修改的文件。

常用安全流程：

```powershell
git status --short
git diff -- app.py
git add app.py
git commit -m "message"
git push origin main
```

## 4. 线上服务

主站：

```text
https://youtube-summarize-0oms.onrender.com
```

Bridge：

```text
https://youtube-summarize-bridge.onrender.com
```

Chrome Web Store 插件页面：

```text
https://chromewebstore.google.com/detail/youtube-transcript-helper/mhfokbdjfongbblejjgafmkmnnepocej
```

注意：Chrome Web Store 页面 URL 里旧 slug 仍可能显示 `youtube-transcript-helper`，但产品名已改为 `ClipBrief AI`。

## 5. Render 环境变量

主站需要的关键环境变量：

```text
OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_API_KEY=<NVIDIA NIM token，不要写入 Git>
OPENAI_SUMMARY_MODEL=deepseek-ai/deepseek-v4-pro
OPENAI_FACT_CHECK_MODEL=deepseek-ai/deepseek-v4-pro
BRIDGE_API_URL=https://youtube-summarize-bridge.onrender.com
UPSTASH_REDIS_REST_URL=<Upstash REST URL>
UPSTASH_REDIS_REST_TOKEN=<Upstash REST token>
DATA_DIR=/data
```

说明：

- `OPENAI_*` 用于总结和事实核查。
- `UPSTASH_*` 目前用于主站留言板持久化。
- `DATA_DIR=/data` 是给 Render Disk 用的，但免费 Render 不支持 disk；没有 disk 时主要靠 Upstash 保存留言板。
- 不要把 token 写入 `settings.json` 后提交。当前历史里已有旧 key 痕迹，后续不要扩大问题。

Bridge 服务环境变量参考 `BRIDGE_API_SETUP.md`：

```text
BRIDGE_STORE_BACKEND=upstash
BRIDGE_API_HOST=0.0.0.0
BRIDGE_TTL_SECONDS=900
BRIDGE_MAX_TRANSCRIPT_CHARS=250000
BRIDGE_API_TOKEN=
BRIDGE_UPSTASH_FALLBACK_ENABLED=1
UPSTASH_REDIS_REST_URL=<Upstash REST URL>
UPSTASH_REDIS_REST_TOKEN=<Upstash REST token>
```

Render 免费实例没有 persistent disk。留言板不要再依赖本地 `guestbook.json` 作为线上持久存储。

## 6. 当前大模型状态

当前默认模型已经从硅基流动切到 NVIDIA NIM：

```text
base_url: https://integrate.api.nvidia.com/v1
summary_model: deepseek-ai/deepseek-v4-pro
fact_check_model: deepseek-ai/deepseek-v4-pro
```

已验证：

- `/models` 能找到 `deepseek-ai/deepseek-v4-pro`。
- 最小 chat completion 能调用成功。

风险：

- 该模型非常慢。测试中 `max_tokens=2` 都用了约 `114s`。
- 完整总结和核查可能会超慢，后续如果用户反馈慢，优先换更快的 NIM 模型，而不是改业务逻辑。

主站调用链：

- `app.py` 读取 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_SUMMARY_MODEL`、`OPENAI_FACT_CHECK_MODEL`。
- `core_logic.py` 通过 OpenAI SDK 的 `base_url` 调用 OpenAI-compatible 接口。
- 不需要为 NVIDIA NIM 单独接 SDK。

## 7. 留言板状态

留言板当前功能：

- 匿名发布留言。
- 所有人可见。
- 直接显示回复，不需要展开。
- 每条留言可回复。
- 每条留言可点赞。
- 管理员可编辑/删除留言。

存储：

- 优先使用 Upstash Redis。
- 无 Upstash 环境变量时回退本地 `guestbook.json`。

实现位置：

```text
app.py
load_guestbook()
save_guestbook()
append_guestbook_message()
append_guestbook_reply()
like_guestbook_message()
render_wish_wall_page()
```

当前 Upstash 简化方案：

- 整个留言板存成一个 JSON key：`clipbrief:guestbook:v1`
- 这是有意的最小实现。留言量很小够用。
- 如果未来留言很多或并发冲突明显，再换 Supabase/Postgres 表。

## 8. Chrome 扩展状态

目录：

```text
chrome_extension_mvp
```

当前 manifest：

```text
name: ClipBrief AI
version: 1.1
```

发布包不是直接上传 `chrome_extension_mvp/`。要用打包脚本生成商店专用包。

打包：

```powershell
cd D:\Workspace\YouTubeSummarizer\chrome_extension_mvp
.\build_packages.ps1
.\preflight_release_check.ps1
```

商店上传 zip：

```text
chrome_extension_mvp/dist/video_transcript_helper_chrome_store_v1.1.zip
```

本地测试商店版：

```text
chrome_extension_mvp/dist/chrome_store_unpacked_v1.1
```

开发版和商店版区别：

- 开发版 `manifest.json` 含 localhost、ngrok、trycloudflare、workers.dev 等开发域名。
- 商店包由 `build_packages.ps1` 自动剥离开发域名和调试代码。
- 不要把开发版直接上传 Chrome Web Store。

权限当前保留：

```text
activeTab
scripting
tabs
clipboardWrite
storage
```

这些权限都仍有用途，不要随便删。

## 9. Chrome Web Store 资料

商店文档：

```text
chrome_extension_mvp/STORE_LISTING.md
chrome_extension_mvp/CHROME_WEB_STORE_CHECKLIST.md
```

当前文案是中英双语。

截图资产目录：

```text
chrome_extension_mvp/store_assets/
```

如果要更新插件：

1. 修改扩展代码。
2. 递增 `chrome_extension_mvp/manifest.json` 版本号。
3. 运行 `build_packages.ps1`。
4. 运行 `preflight_release_check.ps1`。
5. 上传 `video_transcript_helper_chrome_store_vX.zip`。
6. 等 Chrome 审核。

如果只改主站 `app.py`，不需要更新 Chrome 插件。

## 10. 本地开发

建议新电脑步骤：

```powershell
git clone git@github-ytsum:gujianhuan/youtube-summarize.git
cd YouTubeSummarizer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

如果系统没有 `python`，先安装 Python 3.11/3.12。当前旧电脑里有未跟踪 `.python313` 运行时，不要依赖它，也不要提交它。

本地启动主站：

```powershell
streamlit run app.py
```

本地启动 bridge：

```powershell
python bridge_api.py
```

本地常用检查：

```powershell
python -m py_compile app.py core_logic.py bridge_api.py
cd chrome_extension_mvp
node --check background.js
node --check popup.js
node --check content.js
.\build_packages.ps1
.\preflight_release_check.ps1
```

## 11. 事实核查状态

事实核查主要在 `core_logic.py`。

当前思路：

- 快速核查先给少量重要 claim。
- 深度核查可以后台继续。
- 来源输出要区分直接来源、候选来源、仅搜索入口。
- AnySearch 作为条件补强 provider，之前已讨论过用于 Reuters/Bloomberg/AP/FT/WSJ、原始来源、财经政策数据类 claim。

用户对事实核查的要求：

- 不只核查 5 条，要尽量覆盖主要内容。
- 但速度也要控制，不能几百秒才返回。
- 对“暂未定位到直接来源”“候选来源”这类文案要继续优化。

如果继续优化事实核查，优先改：

```text
core_logic.py
search_claim_sources()
fact_check_document_claims()
decide_video_fact_check_plan()
render_fact_check_content()
```

## 12. 已知风险和不要踩的坑

1. 不要把服务端抓 YouTube transcript 当主链路。
   Render/云服务器容易触发 YouTube 429。

2. 不要把 API key/token 提交到 Git。
   用户最近贴过 NVIDIA NIM token 和 Upstash token，应建议轮换。

3. 不要同时启用本地开发版插件和商店版插件。
   两个插件可能同时响应，导致重复打开主站或状态混乱。

4. 不要直接上传开发版扩展目录到 Chrome Web Store。
   必须用 `chrome_store` 包。

5. 不要用 `git add .`。
   当前工作区有大量历史调试文件和浏览器 profile。

6. 不要过度设计留言板。
   目前 Upstash 一个 JSON key 足够。并发冲突真实出现后再换数据库。

7. NVIDIA NIM DeepSeek V4 Pro 可能太慢。
   如果用户反馈总结慢，先换模型，不要先重构总结逻辑。

## 13. 当前建议下一步

优先级从高到低：

1. 在 Render 确认 `OPENAI_*`、`UPSTASH_*` 环境变量已配置，且主站重部署成功。
2. 在线测试：插件提取 transcript -> 主站总结 -> 留言板发布/回复/点赞。
3. 如果 NIM 模型太慢，换更快模型并只改 Render 环境变量。
4. 继续优化插件 transcript 提取速度和成功率。
5. 继续优化事实核查来源质量和耗时。

## 14. 给下一个 Codex 的工作原则

- 默认中文沟通。
- 先查代码再下结论。
- 小改动优先，不要重构全项目。
- 当前用户偏好：能跑通真实链路优先，再做 UI 和文案。
- 涉及 Chrome 插件、Render、GitHub，改完要明确说明是否需要用户手动操作。
- 如果只是主站变更，不要让用户重新打包 Chrome 插件。
- 如果只是扩展变更，必须提醒 Chrome Web Store 审核延迟。

