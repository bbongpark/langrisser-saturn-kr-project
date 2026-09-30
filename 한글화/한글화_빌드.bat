@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo 환경_준비.bat를 먼저 실행하세요.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -B scripts\rebuild.py
if errorlevel 1 (echo 빌드가 완료되지 않았습니다. 위 오류를 확인하세요.) else (echo 한글화 전용 빌드 완료.)
pause
