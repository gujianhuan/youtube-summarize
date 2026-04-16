# Chrome 扩展 MVP

这是一个最小可用的 Chrome 扩展骨架，用于在用户自己的浏览器页面里提取 YouTube / Bilibili 的可见字幕文本。

## MVP 目标

- 在用户自己的浏览器上下文中提取页面可见字幕
- 把字幕复制到剪贴板
- 或自动打开主站的 `✍️ 粘贴字幕` 页签并自动填入文本

## 当前能力

- YouTube：优先尝试读取页面内嵌字幕数据；若失败，再尝试读取 transcript 面板中的可见字幕节点并自动展开
- Bilibili：尝试读取页面中的可见字幕节点
- Popup 中支持：
  - 提取字幕
  - 复制字幕
  - 自动发送到主站
  - 尽量自动触发主站总结

## 当前限制

- 这是 MVP，不保证所有页面结构都能提取成功
- 当前仍是 MVP，YouTube 会优先尝试读取页面内嵌字幕数据；若拿不到，再自动尝试展开 transcript 面板
- YouTube 页面结构变化、字幕轨道不可用或视频本身无公开字幕时，仍可能失败
- 视频画面中出现“硬字幕”不代表 YouTube 提供了可提取 transcript；若无公开字幕轨道，扩展仍会失败
- Bilibili 当前仍更依赖页面中已经可见的字幕节点
- 当前不直接走主站 API，但会自动打开主站并尽量填入 transcript 与来源链接

## 安装方式

1. 打开 Chrome 扩展管理页面：`chrome://extensions/`
2. 打开“开发者模式”
3. 选择“加载已解压的扩展程序”
4. 选择当前目录 `chrome_extension_mvp`

## 更新方式

- 当前如果你使用的是“加载已解压的扩展程序”，**每次代码更新后都需要在 `chrome://extensions/` 里点一次刷新**
- 现在项目里已经提供开发辅助脚本：

```powershell
Set-Location "D:\Program Files\Trae\YouTubeSummarizer\chrome_extension_mvp"
.\refresh_dev.ps1
```

- 这个脚本会：
  - 读取当前扩展版本
  - 重新打包 `chrome_extension_mvp.zip`
  - 提示你去 Chrome 扩展页刷新

注意：

- **加载目录模式不能真正自动更新**
- 真正的自动更新需要后续走：
  - Chrome Web Store
  - 或自托管 CRX + `update_url`

## 建议使用流程

1. 打开 YouTube / Bilibili 视频页面
2. YouTube 可直接点击扩展尝试自动展开 transcript；Bilibili 建议先展开字幕面板
3. 点击扩展图标
4. 点击“提取字幕”
5. 点击“发送到主站”
6. 主站会自动打开并尽量填入 transcript
7. 扩展会尽量自动触发主站总结；若失败，再手动点一次总结按钮

## 下一步可增强

- 直接调用主站 API 上传 transcript
- 保存最近一次提取结果
- 支持更多页面结构和字幕来源
