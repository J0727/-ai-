@echo off
chcp 65001 >nul
title 智汇研途 - 公网访问一键启动
cd /d "%~dp0..\backend"

echo ============================================================
echo   智汇研途 - 让别人也能访问
echo ============================================================
echo.
echo [1/2] 启动后端（监听 0.0.0.0:8011，局域网与隧道均可接入）...
if not exist ".venv\Scripts\python.exe" (
  echo   找不到 .venv\Scripts\python.exe，请确认项目目录未被移动。
  pause & exit /b 1
)
start "智汇研途-后端" cmd /c ".venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8011 --log-level warning"
timeout /t 5 >nul

echo [2/2] 建立公网隧道（约 5-10 秒，请等待出现 https 地址）...
echo.
echo   本机自用：  http://127.0.0.1:8011/
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%j in ("%%i") do echo   同一 WiFi：http://%%j:8011/
)
echo.
echo   公网地址：请看下面 Cloudflare 输出的 https://xxx.trycloudflare.com
echo   （该地址每次重启都会变，把新地址发给对方即可）
echo.
echo ------------------------------------------------------------
echo   注意：本窗口和「智汇研途-后端」窗口都不能关，
echo         电脑也不能睡眠，否则别人就打不开了。
echo ------------------------------------------------------------
echo.

if exist "%~dp0bin\cloudflared.exe" (
  "%~dp0bin\cloudflared.exe" tunnel --url http://127.0.0.1:8011 --no-autoupdate
) else (
  echo 未找到 cloudflared：请把 cloudflared.exe 放到 %~dp0bin\ 目录后重试。
)

echo.
echo 隧道已退出。
pause
