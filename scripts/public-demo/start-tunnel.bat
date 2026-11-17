@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 智汇研途 - 公网演示隧道（Cloudflare，免费无需注册）

set "BACKEND=http://127.0.0.1:8000"
set "DIR=%~dp0"
set "CF=%DIR%cloudflared.exe"
set "MIRROR=https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

echo ============================================================
echo   公网演示隧道：把本机 8000 端口映射成一个 https 地址
echo   免费、不需要注册账号、不需要信用卡
echo ============================================================
echo.

rem ---------- 1. 检查后端 ----------
echo [..] 检查后端是否已启动（%BACKEND%）...
curl -s -m 3 "%BACKEND%/api/health" >nul 2>&1
if errorlevel 1 (
    echo [x] 后端没启动。
    echo     请先双击运行：backend\启动后端.bat
    echo     等窗口出现 "Application startup complete" 后再运行本脚本。
    echo.
    pause
    exit /b 1
)
echo [ok] 后端正常

rem ---------- 2. 准备 cloudflared ----------
if exist "%CF%" goto run
echo [..] 首次运行，正在下载 cloudflared（走国内镜像，约 3~15 分钟）...
curl -L --connect-timeout 15 --retry 2 -o "%CF%" "%MIRROR%"
if not exist "%CF%" (
    echo [x] 下载失败。请手动下载后放到本目录：
    echo     %MIRROR%
    echo     另存为：%CF%
    pause
    exit /b 1
)
echo [ok] 下载完成

:run
echo.
echo [..] 正在建立隧道，请稍等 5~15 秒...
echo     下面出现的 https://xxxx.trycloudflare.com 就是公网地址
echo     把这个地址发给评委即可；关闭本窗口隧道就断开
echo ------------------------------------------------------------
echo.

"%CF%" tunnel --url %BACKEND% --no-autoupdate

echo.
echo [x] 隧道已断开（窗口关闭或网络中断）
pause
