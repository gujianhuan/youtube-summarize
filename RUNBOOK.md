# RUNBOOK

## 1. 文档目标
本文件用于记录项目的日常运行方法、发布方法、联调方法和常见故障排查步骤，作为项目操作手册使用。

## 2. 项目目录
推荐项目路径：

```text
D:\Program Files\Trae\YouTubeSummarizer
```

若换电脑，尽量保持相同路径，以减少虚拟环境、插件、本地工具对绝对路径的依赖问题。

## 3. 常用启动步骤
### 3.1 进入项目目录

```powershell
cd "D:\Program Files\Trae\YouTubeSummarizer"
```

### 3.2 检查基础环境

```powershell
git --version
python --version
ffmpeg -version
```

### 3.3 启动项目
如果当前环境已经可用，优先直接尝试：

```powershell
streamlit run app.py
```

如果 `streamlit` 命令不可用，则需要先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

## 4. 虚拟环境处理
### 4.1 激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4.2 如果激活失败
可能原因：
- 换电脑后路径变化
- 旧虚拟环境引用了旧机器的解释器路径

处理方式：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 5. 日常开发常用命令
### 5.1 查看 Git 状态

```powershell
git status
```

### 5.2 查看当前分支

```powershell
git branch --show-current
```

### 5.3 拉取最新代码

```powershell
git pull origin main
```

### 5.4 提交本地改动

```powershell
git add .
git commit -m "你的提交说明"
git push origin main
```

## 6. Render 发布流程
### 6.1 本地修改后发布
1. 在本地完成改动。
2. 验证关键功能。
3. 提交代码到 `main`。
4. 推送到远端。
5. Render 拉取 `main` 后开始部署。

### 6.2 常用命令

```powershell
git status
git add .
git commit -m "你的提交说明"
git push origin main
```

### 6.3 发布前最低检查项
- `app.py` 无明显语法错误
- `core_logic.py` 无明显语法错误
- 关键主链路至少做一次手工验证
- 没把敏感文件误提交到仓库

## 7. 迁移到新电脑后的第一轮自检
### 7.1 基础检查

```powershell
git status
python --version
ffmpeg -version
```

### 7.2 启动检查

```powershell
streamlit run app.py
```

### 7.3 业务链路检查
优先验证：
1. 首页是否正常打开
2. 普通视频总结是否可用
3. 内容资产库是否能读取历史
4. 订阅列表是否还在
5. “检查所有订阅更新”是否正常
6. 插件桥接是否可用
7. 本地工具兜底是否可用

## 8. 本地数据与关键文件
以下文件对本地使用很重要：
- `history.json`
- `subscriptions.json`
- `.env`
- `.streamlit/secrets.toml`
- 本地工具相关配置文件

注意：
- 历史和订阅如果丢了，功能还能跑，但你的本地数据会丢失。
- 敏感配置不要公开传播。

## 9. 插件联调手册
### 9.1 目标
用于验证 Chrome 插件 -> bridge -> 主站总结 的主链路。

### 9.2 基本流程
1. 打开目标视频页面。
2. 启动并加载 Chrome 插件。
3. 插件提取文本。
4. 通过 bridge API 上传 payload。
5. 主站读取 `ext_payload_id`。
6. 自动注入文本并触发总结。

### 9.3 重点检查项
- 插件是否提取到正确文本，而不是页面推荐区噪音
- bridge API 是否可访问
- 主站是否成功读取 payload
- 是否成功自动开始总结

### 9.4 常见问题
- 插件提取到杂讯：优先检查页面选择器或提取逻辑
- bridge 无法读取：检查 payload id、bridge 服务状态、网络环境
- 总结未自动触发：检查 query 参数和主站自动注入逻辑

## 10. 本地工具联调手册
### 10.1 目标
用于在无可用字幕时，通过本地工具完成音频获取和转写。

### 10.2 基本流程
1. 输入视频 URL。
2. 本地工具调用 `yt-dlp` 获取资源。
3. 用 `ffmpeg` 处理音频。
4. 使用 Whisper 做转写。
5. 将转写文本回传主站。

### 10.3 检查项
- `yt-dlp` 是否可用
- `ffmpeg` 是否可用
- Whisper 模型是否能正常加载
- 音频临时文件是否能生成
- 转写结果是否能正常送入总结链路

### 10.4 常见问题
- `yt-dlp` 报错：多为网络、代理、Cookie、平台风控问题
- `ffmpeg` 找不到：多为环境变量问题
- 转写很慢：多为本地硬件性能限制
- GPU 不可用：多为显卡过旧或 CUDA 兼容性问题

## 11. 内容资产库日常使用说明
### 11.1 当前用途
- 汇总单次处理、手动粘贴、扩展桥接和定时任务产出的内容结果

### 11.2 当前行为
- 支持搜索历史记录
- 支持全文搜索
- 有历史时才显示“清空历史”
- 会显示历史总数与当前命中数

## 12. 订阅自动化日常使用说明
### 12.1 当前目标
- 管理频道订阅
- 检查最新动态
- 对新视频进行后续处理

### 12.2 已知重要规则
- 部分频道可能既发直播回放，也发普通视频
- 当前逻辑已修复为按发布时间稳定排序，而不是简单按抓取顺序返回

### 12.3 若发现“不是最新”
优先检查：
- 当前代码是否已经包含最新修复
- 是否真的拉到远端最新提交
- 当前目标频道是否因网络、Cookie、平台风控导致抓取异常

## 13. 事实核查相关说明
### 13.1 当前行为
- 对明显属于测试文本、链路验证文本、产品演示文本的内容，默认不做新闻事实核查
- 对正常新闻/事件类文本，保留事实核查能力

### 13.2 若出现误判
优先检查：
- 文本内容是否包含大量“测试 / 验证 / bridge / payload / transcript”等特征
- 最近是否改过事实核查触发规则

## 14. 常见故障排查顺序
建议排查顺序固定如下：
1. 是否是环境问题
2. 是否是依赖问题
3. 是否是网络/代理问题
4. 是否是平台风控问题
5. 是否是本地文件丢失
6. 是否是最近代码改动引起

## 15. 常见故障与建议动作
### 15.1 `streamlit run app.py` 启动失败
- 先看虚拟环境是否可用
- 再看依赖是否完整
- 再看最近是否有语法错误

### 15.2 `ffmpeg` 找不到
- 重新安装或重新加 PATH

### 15.3 订阅更新结果为空
- 检查网络和代理
- 检查目标频道 URL 是否有效
- 检查 `yt-dlp` 是否工作正常

### 15.4 插件桥接失败
- 检查插件提取结果
- 检查 bridge 服务
- 检查主站读取 payload 的逻辑

### 15.5 本地转写太慢
- 降低本地模型规模
- 减少同时运行任务数
- 优先走云端总结，减少本地压力

## 16. 新会话继续协作的推荐方式
换电脑或新会话后，建议优先让我读取以下文件：
- `AGENT_CONTEXT.md`
- `MIGRATION_NOTES.md`
- `COMMERCIALIZATION_PLAN.md`
- `RUNBOOK.md`

推荐直接提供：
1. 当前提交哈希
2. 当前报错
3. 当前目标
4. 上述 4 份文档

## 17. 备注
本文件主要服务当前项目阶段，后续随着商业化推进，需要逐步拆分为：
- 开发运行手册
- 运维发布手册
- 插件联调手册
- 本地工具联调手册
- 生产事故排障手册
