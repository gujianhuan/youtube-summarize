@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "VBS_SCRIPT=%SCRIPT_DIR%打开本地转写助手.vbs"

wscript "%VBS_SCRIPT%"
if errorlevel 1 (
    echo 启动失败，请检查 Python 环境后重试。
    pause
)
