# 扩展发布说明

本目录当前按 `Chrome-only` 发布流程维护，仅生成 `Chrome` 发布包和本地联调目录。

## 生成发布产物

在 `chrome_extension_mvp` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_packages.ps1
```

执行后会在 `dist` 目录生成：

- `video_transcript_helper_chrome_v<version>.zip`
- `chrome_unpacked_v<version>/`
- `video_transcript_helper_chrome_store_v<version>.zip`
- `chrome_store_unpacked_v<version>/`
- `release_info_v<version>.json`

## 使用方式

### Chrome

- 本地测试：在 `chrome://extensions/` 里加载 `chrome_unpacked_v<version>` 目录
- 商店包测试：在 `chrome://extensions/` 里加载 `chrome_store_unpacked_v<version>` 目录
- 上架提交：上传 `video_transcript_helper_chrome_store_v<version>.zip` 到 `Chrome Web Store`

商店专用包会移除本地/隧道开发域名，并去掉 `debugger` 权限，以降低审核风险。开发包仍保留本地联调能力。

## 当前范围

- 当前版本只承诺 `Chrome` 安装、联调和发布
- `Edge / Firefox` 暂不作为本期验收项，也不纳入当前上架物料

## 发布前检查

- 确认 `manifest.json` 的版本号已经更新
- 确认商店包 manifest 不包含 `debugger`、`localhost`、`127.0.0.1`、`ngrok`、`trycloudflare`、`workers.dev`
- 在 `Chrome` 的 YouTube 视频页手动测试：
  - 提取字幕
  - 复制文本
  - 一键总结
- 确认主站地址与 Bridge 地址配置正确
- 确认 `dist/release_info_v<version>.json` 中的路径与版本一致
