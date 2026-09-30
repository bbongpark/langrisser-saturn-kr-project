@echo off
setlocal
chcp 65001 >nul
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1" -InputCue "%~1"
)
set "patch_exit=%errorlevel%"
echo.
pause
exit /b %patch_exit%
