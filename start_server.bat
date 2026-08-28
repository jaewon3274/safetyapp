@echo off
chcp 65001 >nul 2>&1
title IPARK Safety System

:: 기존 포트 5000 프로세스 정리
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":5000 " ^| find "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

cd /d "%~dp0"

:: 백그라운드로 Flask 서버 시작
start /B python app.py > server.log 2>&1

:: 3초 대기 후 브라우저 열기
timeout /t 3 /nobreak >nul
start "" http://localhost:5000

exit
