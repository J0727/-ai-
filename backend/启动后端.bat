@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   智汇研途 - 后端服务启动中...
echo   启动后请保持本窗口打开
echo   关闭本窗口 = 停止后端服务
echo ========================================
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo 后端已停止。按任意键关闭窗口...
pause >nul
