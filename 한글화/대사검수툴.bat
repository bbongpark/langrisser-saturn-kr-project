@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo 환경_준비.bat를 먼저 실행하세요.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -B scripts\dialogue_editor.py
pause
