# 版本发布说明

## v0.1.54

### 新增

- 收敛当前发布目标为 `Chrome-only`
- 新增统一打包脚本 `build_packages.ps1`
- 新增发布说明 `RELEASE_GUIDE.md`
- 新增 `dist/release_info_v0.1.54.json` 发布信息文件
- 新增 `Chrome` 解压目录产物，方便本地安装和商店提审前检查
- 新增 `16/32/48/128` 扩展图标并接入 `manifest`

### 优化

- 扩展发布文档、商店文案和预检流程统一改为围绕 `Chrome` 发布
- 打包流程只保留 `Chrome` 发布包与本地联调目录

### 当前已知事项

- 商店展示文案、简介、截图说明需要按平台后台要求逐项填写
- 正式上架前，建议至少在 `Chrome` 中手测一次：
  - 提取字幕
  - 复制文本
  - 一键总结

### 建议提交备注

- Chrome Web Store:
  - Focus the extension release flow on Chrome-only packaging and validation
  - Align docs, listing copy, and local refresh steps with the Chrome launch scope
