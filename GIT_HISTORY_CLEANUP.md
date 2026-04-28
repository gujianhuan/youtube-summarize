# Git 历史瘦身说明

## 现状判断

- Render 线上仍停在旧提交 `561f9b7`
- 远程 `origin/main` 也仍停在 `561f9b7`
- 本地 `HEAD` 已前进到 `e3c9370`
- 说明问题不在 Render 本身，而在于新历史没有真正推送到远程

## 根因

当前 `561f9b7..HEAD` 这段待推送历史里，仍然包含大量构建产物二进制，即使最新提交已经把它们从索引移除了，这些大文件依然存在于历史提交中。

已确认的代表性大文件包括：

- `dist/LocalTranscriptHelper-win-x64.zip` 约 `274 MB`
- 多个 `dist/LocalTranscriptHelperOnline/...` 二进制在 `58 MB` 到 `87 MB`
- 多个 `build/windows_portable/...` 二进制在 `24 MB` 左右

这就是为什么：

- Git 推送体积仍然高达约 `430 MB`
- 远程分支没有前进
- Render 一直只能部署旧提交

## 这次需要清理的历史路径

- `build/`
- `dist/`
- `local_cli_mvp_output/`
- `tmp_*`
- `.tmp_*`
- `chrome_extension_mvp.zip`

## 推荐做法

不要在当前工作仓库直接改写历史。正确姿势是在一个单独的 mirror 克隆里做清理，再确认无误后强推远程。

仓库里已经补了一份 Windows 脚本：

- [git_history_cleanup.ps1](file:///d:/Program%20Files/Trae/YouTubeSummarizer/scripts/git_history_cleanup.ps1)

## 执行步骤

1. 先确保当前工作区是干净的
2. 在 PowerShell 里进入仓库根目录
3. 执行下面的命令

```powershell
Set-Location "D:\Program Files\Trae\YouTubeSummarizer"
.\scripts\git_history_cleanup.ps1 -InstallFilterRepo
```

4. 脚本会自动：
   - 创建 `.bundle` 备份
   - 克隆一个 mirror 仓库
   - 安装 `git-filter-repo`
   - 清掉上述历史路径
   - 执行 `git gc`
   - 打印后续验证和强推命令

## 强推前必须确认

在 mirror 仓库里至少检查下面几项：

```powershell
git count-objects -vH
git log --oneline --stat -5
git log -- build dist local_cli_mvp_output
git remote -v
```

## 最终推送

确认无误后，再在 mirror 仓库里执行：

```powershell
git push --force-with-lease origin refs/heads/main:refs/heads/main
```

## 风险点

- 这是**改写远程历史**，所有协作者都需要重新同步
- Render 会基于新历史重新拉取，部署会重新触发
- 如果本地还有未备份提交，强推前一定先保留 bundle 备份
- 若有其它 CI、Webhook、自动发布流程依赖旧 commit SHA，都会失效

## 建议顺序

1. 先提交当前修复：恢复 `manifest.json`、补充 `.gitignore`
2. 再执行历史瘦身脚本
3. 确认远程 `main` 已前进
4. 最后重新观察 Render 是否开始部署
