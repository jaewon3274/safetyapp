@echo off
chcp 65001 >nul 2>&1
title IPARK Safety System Server

:: 이미 실행 중인 서버가 있으면 종료
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5000" ^| find "LISTENING"') do (
    echo 기존 서버 종료 중...
    taskkill /F /PID %%a >nul 2>&1
)

cd /d "%~dp0"
echo.
echo  ============================================================
echo   IPARK리조트 안전관리시스템 서버 시작
echo   http://localhost:5000
echo  ============================================================
echo.

:: 서버 백그라운드 실행
start /B python app.py > server.log 2>&1

:: 서버 준비 대기 (3초)
timeout /t 3 /nobreak >nul

:: 브라우저 자동 열기
start "" "http://localhost:5000"

echo  서버가 시작되었습니다. 브라우저가 자동으로 열립니다.
echo  이 창을 닫아도 서버는 계속 실행됩니다.
echo.
echo  서버 종료하려면: taskkill /F /IM python.exe
echo.
timeout /t 5 /nobreak >nul
exit
