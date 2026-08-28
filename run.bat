@echo off
chcp 65001 > nul
title Smart DMS — 문서 관리 시스템

echo.
echo ============================================================
echo    Smart DMS -- 문서 관리 시스템 (Python Flask)
echo ============================================================
echo.

:: Python 설치 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python 이 설치되어 있지 않습니다.
    echo Python 을 먼저 설치해주세요: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 의존성 설치
echo [1/3] pip 패키지 설치 중 (flask, openpyxl)...
pip install flask openpyxl werkzeug --quiet --upgrade
if errorlevel 1 (
    echo [오류] 패키지 설치 실패. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
)

echo [2/3] 패키지 설치 완료!
echo [3/3] 서버 시작 중...
echo.
echo   브라우저 주소: http://localhost:5000
echo   종료: 이 창에서 Ctrl+C
echo.

:: 서버 실행
python app.py

pause
