# Chrome Web Store 上架清单

本清单按当前 `Chrome-only` 发布策略整理，目标是让你可以直接照着准备物料、填表和做发布前复核。

## 1. 上架目标
- 当前正式支持平台：`Chrome`
- 当前扩展目录：`chrome_extension_mvp`
- 当前上架包：`dist/video_transcript_helper_chrome_v<version>.zip`
- 当前定位：在 YouTube 当前视频页提取 transcript，并发送到 ClipBrief AI 总结和核查

## 2. 提交前必须准备

### 2.1 安装包
- [ ] 执行 `build_packages.ps1`
- [ ] 确认生成开发包 `dist/video_transcript_helper_chrome_v<version>.zip`
- [ ] 确认生成商店包 `dist/video_transcript_helper_chrome_store_v<version>.zip`
- [ ] 确认 `manifest.json` 里的版本号与 zip 文件名一致
- [ ] 确认 zip 内包含 `manifest.json`、`popup.html`、`popup.js`、`background.js`、`content.js`、`icons/`
- [ ] 确认上架只上传 `video_transcript_helper_chrome_store_v<version>.zip`

### 2.2 图标素材
- [ ] `16x16`
- [ ] `32x32`
- [ ] `48x48`
- [ ] `128x128`
- [ ] 图标与扩展当前品牌一致，不出现旧名称或旧 logo

### 2.3 商店截图
- [ ] 截图 1：插件弹窗首页
- [ ] 截图 2：提取成功后的弹窗状态
- [ ] 截图 3：后台发送状态
- [ ] 截图 4：主站总结页
- [ ] 截图内容全部基于 `Chrome`，不要出现 `Edge` 或 `Firefox`

### 2.4 文案来源
- [ ] 扩展名称、短描述、详细描述以 `STORE_LISTING.md` 为准
- [ ] 发布说明以 `RELEASE_NOTES.md` 为准
- [ ] 发布流程以 `RELEASE_GUIDE.md` 为准

## 3. Chrome Web Store 填写建议

### 3.1 基本信息
- 名称：`ClipBrief AI`
- 英文名：`ClipBrief AI`
- 简短描述：`在 YouTube 视频页提取字幕文本，并发送到 ClipBrief AI 生成摘要和来源核查。`

### 3.2 详细描述
建议直接基于 `STORE_LISTING.md` 填写，至少覆盖这些点：
- 自动尝试读取 YouTube 页面可用字幕
- 提取失败时提供更清晰的状态提示
- 支持复制文本
- 支持一键发送到 ClipBrief AI 主站
- 关闭弹窗后后台流程仍可继续
- 当前正式支持 `Chrome`

### 3.3 分类与可见性
- 类别建议：`Productivity`
- 语言：优先 `zh-CN`，如需英文可补充英文版描述
- 可见性：先按小范围试用策略选择，避免未验证完成就公开放量

## 4. 隐私与权限复核

### 4.1 需要人工核对的点
- [ ] 扩展只声明了当前功能必需权限
- [ ] 商店包不包含 `debugger` 权限
- [ ] 商店包不包含 `localhost`、`127.0.0.1`、`ngrok`、`trycloudflare`、`workers.dev` 等开发域名
- [ ] 描述中明确只支持 YouTube
- [ ] 描述中明确当前正式支持 `Chrome`
- [ ] 最近一次提取结果和任务状态仅保存在浏览器本地存储
- [ ] 不要在商店描述里承诺未上线的平台或功能

### 4.2 隐私说明建议
可直接使用 `STORE_LISTING.md` 的这版口径：
- 扩展主要访问用户当前打开的 YouTube 页面，用于提取字幕文本
- 最近一次提取结果和任务状态保存在浏览器本地存储，便于弹窗重开后恢复
- 扩展不会主动读取与当前功能无关的网站内容

## 5. 发布前最终验证

### 5.1 自动化回归
- [ ] 启动本地主站与 bridge
- [ ] 执行 `.\.python313\python.exe .\run_chrome_release_regression.py`
- [ ] 确认 `chrome_release_regression_summary.json` 中 `release_ready` 为 `true`

### 5.2 手工回归
- [ ] `chrome://extensions/` 能正常加载扩展
- [ ] 在 YouTube 视频页点击“提取字幕”成功
- [ ] “复制文本”可正常使用
- [ ] “一键总结”能打开主站并完成总结链路
- [ ] 错误状态下提示文案可理解

## 6. 实际提交顺序
1. 运行打包脚本，生成最新开发包与商店包 zip。
2. 跑自动化回归和一轮手工回归。
3. 整理图标、截图、简短描述、详细描述、隐私说明。
4. 登录 `Chrome Web Store Developer Dashboard` 创建或更新条目。
5. 上传 `video_transcript_helper_chrome_store_v<version>.zip`。
6. 填写商店字段并上传截图素材。
7. 复核权限、隐私说明和支持平台描述。
8. 提交审核。

## 7. 本次版本建议结论
- 只提交 `Chrome` 包
- 不在商店文案里提 `Edge`、`Firefox`
- 先按小范围试用发布
- 审核通过后再决定是否公开推广
