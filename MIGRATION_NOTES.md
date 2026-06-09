# MIGRATION_NOTES

## 1. 目标
本文件用于指导将当前项目从旧电脑迁移到新电脑，并在迁移后快速恢复可运行状态。

## 2. 推荐迁移方式
当前阶段优先推荐：
- 直接复制整个 `D:\Program Files\Trae` 目录到新电脑。
- 尽量保持相同路径，减少虚拟环境、插件、本地工具对绝对路径的依赖问题。

推荐路径：

```text
D:\Program Files\Trae
```

## 3. 迁移前准备
### 3.1 关闭运行中的程序
迁移前建议关闭：
- Trae IDE
- Streamlit 运行窗口
- Python 后台进程
- 本地音频转写工具
- 可能占用项目文件的终端

### 3.2 确认代码已入库
至少确认当前重要变更已提交并推送：

```powershell
git status
git log -1 --oneline
git remote -v
```

## 4. 需要保留的重要内容
### 4.1 项目代码
- 整个 `Trae` 目录

### 4.2 本地数据
以下文件若存在，迁移后应一并保留：
- `history.json`
- `subscriptions.json`
- 其他本地任务/缓存/配置文件

### 4.3 敏感配置
若项目中存在以下配置，请注意安全：
- `.env`
- `.streamlit/secrets.toml`
- 本地 API Key
- 代理配置
- 第三方服务 Token

注意：
- 不要把敏感信息公开传输到不可信渠道。
- 若使用网盘或聊天工具中转，需注意泄漏风险。

## 5. 新电脑的基础环境
即使复制整个目录，新电脑仍建议具备以下系统级依赖：
- Git
- Python
- FFmpeg
- Chrome / Edge / Firefox（若继续使用浏览器扩展）

建议优先检查：

```powershell
git --version
python --version
ffmpeg -version
```

## 6. 迁移后的第一轮自检
进入项目目录：

```powershell
cd "D:\Program Files\Trae\YouTubeSummarizer"
```

执行以下检查：

```powershell
git status
python --version
ffmpeg -version
```

如需启动项目：

```powershell
streamlit run app.py
```

若 `streamlit` 命令不可用，再检查虚拟环境是否需要重建。

## 7. 最常见问题
### 7.1 虚拟环境失效
现象：
- `.venv` 无法激活
- `python` / `streamlit` 指向旧路径

处理建议：
- 不先急着重装全部依赖。
- 若确实失效，再重建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 7.2 FFmpeg 不可用
现象：
- `ffmpeg -version` 找不到命令

处理建议：
- 重新安装 FFmpeg
- 或重新配置系统 `PATH`

### 7.3 浏览器扩展失效
现象：
- 插件目录路径变化，扩展无法加载

处理建议：
1. 按当前浏览器打开扩展页：
   - Chrome：`chrome://extensions/`
   - Edge：`edge://extensions/`
   - Firefox：`about:debugging#/runtime/this-firefox`
2. 重新加载最新解压目录或重新临时载入 `manifest.json`
3. 若需要重新打包，执行 `chrome_extension_mvp\build_packages.ps1`

### 7.4 本地工具路径失效
现象：
- 本地转写工具无法启动
- 路径引用旧机器位置

处理建议：
- 检查本地工具目录是否完整复制
- 检查依赖是否仍可用
- 必要时重新配置工具路径

## 8. 迁移后优先验证的 5 条链路
1. 主站页面能正常打开。
2. 普通视频总结能正常跑通。
3. 内容资产库能看到历史记录。
4. 订阅列表和“检查所有订阅更新”能工作。
5. 插件桥接或本地工具兜底链路能工作。

## 9. 最近重要提交参考
- 最近一次明确记录并已推送的提交：
  - `6c890dca15a4bf713f727ad3cb63487d774c717b`
  - `Fix subscription latest updates and library UI`

## 10. 若迁移后与 AI 继续协作
建议把以下信息直接发给新会话：
1. `AGENT_CONTEXT.md`
2. 本文件 `MIGRATION_NOTES.md`
3. 当前报错截图或终端日志
4. `git status`
5. `python --version`

## 11. 推荐迁移策略总结
### 最省事策略
- 直接复制整个 `Trae` 目录。
- 到新电脑后优先试跑。
- 有报错再逐项修。

### 更稳策略
- 复制整个目录。
- 同时保留 Git 远端代码。
- 真跑不起来时再重建虚拟环境。

## 12. 风险提示
- 整目录复制虽然简单，但不是最干净的方式。
- 最容易出问题的是：
  - 虚拟环境路径
  - 系统依赖路径
  - 插件路径
  - 本地工具绝对路径
- 这些问题通常都可修复，不是阻断性风险。
