@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

set "HOST=%~1"
if "%HOST%"=="" set /p "HOST=请输入服务器公网 IP（例如 139.224.206.77）: "
if "%HOST%"=="" goto :end

where bash >nul 2>nul
if errorlevel 1 (
    echo [x] 没找到 bash，请先安装 Git for Windows：https://git-scm.com/download/win
    goto :end
)

echo.
echo ========================================
echo   部署目标：%HOST%
echo   下面会提示输入 root 密码
echo ========================================
echo.
bash "%~dp0deploy-remote.sh" "%HOST%"

:end
echo.
pause
