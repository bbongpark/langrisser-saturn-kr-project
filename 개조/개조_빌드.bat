@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -B scripts\rebuild.py
if errorlevel 1 (echo 빌드가 완료되지 않았습니다. 위 오류를 확인하세요.) else (echo 개조 빌드 완료.)
pause
