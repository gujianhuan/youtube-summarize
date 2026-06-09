# YouTubeSummarizer

一个以视频文本获取、字幕转写、AI 总结和订阅自动化为核心的项目。当前形态以 `Streamlit` 为主站入口，围绕 YouTube / Bilibili 内容处理建立了插件桥接、本地工具兜底、事实核查、历史沉淀和订阅自动化能力。

## 1. 当前定位
- 当前阶段：功能验证已基本跑通，正在向更可维护、更可迁移、可商业化重构的方向演进。
- 当前形态：单体 Python / Streamlit 项目。
- 当前主链路：
  - 优先：`Chrome` 浏览器扩展提取文本 -> bridge -> 主站总结
  - 兜底：本地工具抓音频 -> Whisper 转写 -> 主站总结

## 2. 项目能力概览
- 单视频处理
- 手动粘贴字幕总结
- 文档总结
- 事实核查
- 内容资产库
- 订阅自动化
- 后台任务中心
- 本地工具兜底
- 浏览器扩展桥接

## 3. 目录说明
- `app.py`
  - 主站入口，负责页面与大部分业务编排
- `core_logic.py`
  - 核心处理逻辑，包括视频信息获取、字幕/转写/总结/事实核查等能力
- `bridge_api.py`
  - bridge API 服务
- `task_runner.py`
  - 任务执行相关逻辑
- `local_fetch_node.py`
  - 本地抓取节点相关逻辑
- `chrome_extension_mvp/`
  - 浏览器扩展源码，当前以 `Chrome-only` 发布为目标
- `local_cli_mvp/`
  - 本地转写工具与打包脚本
- `shared/`
  - 共享契约定义
- `tests/`
  - 自动化测试

## 4. 文档入口
建议按下面顺序阅读文档。

### 4.1 项目总览
- [AGENT_CONTEXT.md](./AGENT_CONTEXT.md)
  - 当前项目状态、已完成事项、已知风险、后续建议
- [ARCHITECTURE.md](./ARCHITECTURE.md)
  - 系统结构、模块边界、主链路、部署形态、演进方向

### 4.2 运行与迁移
- [RUNBOOK.md](./RUNBOOK.md)
  - 日常运行、发布、联调、排障手册
- [MIGRATION_NOTES.md](./MIGRATION_NOTES.md)
  - 从旧电脑迁移到新电脑的操作说明

### 4.3 产品与商业化
- [COMMERCIALIZATION_PLAN.md](./COMMERCIALIZATION_PLAN.md)
  - 商业化改造初版骨架
- [PRODUCT_EXECUTION_PRD.md](./PRODUCT_EXECUTION_PRD.md)
  - 产品执行与落地需求
- [PRODUCT_STRATEGY_TRANSCRIPT.md](./PRODUCT_STRATEGY_TRANSCRIPT.md)
  - 相关产品策略材料

### 4.4 插件 / bridge / 本地节点
- [BRIDGE_API_SETUP.md](./BRIDGE_API_SETUP.md)
  - bridge API 搭建与使用说明
- [BRIDGE_CONTRACT_MIGRATION.md](./BRIDGE_CONTRACT_MIGRATION.md)
  - bridge contract 迁移说明
- [LOCAL_FETCH_NODE_SETUP.md](./LOCAL_FETCH_NODE_SETUP.md)
  - 本地抓取节点说明

### 4.5 其他历史文档
- [GIT_HISTORY_CLEANUP.md](./GIT_HISTORY_CLEANUP.md)
- [feasibility_report.md](./feasibility_report.md)

## 5. 快速启动
进入项目目录：

```powershell
cd "D:\Program Files\Trae\YouTubeSummarizer"
```

尝试直接启动：

```powershell
streamlit run app.py
```

若 `streamlit` 命令不可用，再激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

## 6. 常用检查命令

```powershell
git status
python --version
ffmpeg -version
```

## 7. 当前已确认的重要事实
- 浏览器扩展 -> bridge -> 主站总结链路以 `Chrome` 为当前正式支持平台。
- 已收紧事实核查触发条件，测试文本默认不做新闻核查。
- 已修复“检查所有订阅更新”命中旧内容的问题，当前按发布时间稳定排序。
- 已优化内容资产库空状态与筛选栏。

## 8. 当前最适合的使用方式
- 适合继续开发、调试、验证主链路。
- 适合在本地或 Render 环境下继续迭代。
- 不适合直接把当前单体形态当成正式多用户商业化架构。

## 9. 如果是新电脑 / 新会话
优先读取以下文件：
1. `README.md`
2. `AGENT_CONTEXT.md`
3. `ARCHITECTURE.md`
4. `RUNBOOK.md`
5. `MIGRATION_NOTES.md`
6. `COMMERCIALIZATION_PLAN.md`

## 10. 后续维护建议
- 关键决策尽量文档化并提交到 Git。
- 避免只把重要上下文留在聊天记录里。
- 若后续进入商业化阶段，建议优先推进：
  - 用户系统
  - 数据库化
  - 业务层与 AI 处理层拆分
