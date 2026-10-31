@echo off
cd /d "%~dp0"
echo ========================================
echo   Zhihui Yantu - Starting backend...
echo   Keep this window OPEN while using.
echo   Close this window to STOP the server.
echo ========================================
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo Backend stopped. Press any key to close...
pause >nul
