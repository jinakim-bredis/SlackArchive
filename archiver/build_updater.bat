@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo =============================================
echo  Slack 증분 업데이트 — PyInstaller 빌드
echo =============================================
echo.

if not exist "..\slackdump.exe" (
    echo [오류] ..\slackdump.exe 를 찾을 수 없습니다.
    pause
    exit /b 1
)

echo [1/3] PyInstaller 설치 확인...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo [오류] pip install pyinstaller 실패
    pause
    exit /b 1
)

echo [2/3] 빌드 시작...
pyinstaller --onefile --windowed ^
    --add-binary "..\slackdump.exe;." ^
    --name SlackUpdater ^
    --clean ^
    updater.py

if errorlevel 1 (
    echo.
    echo [오류] PyInstaller 빌드 실패
    pause
    exit /b 1
)

echo.
echo [3/3] 완료!
echo =============================================
echo  결과물: dist\SlackUpdater.exe
echo.
echo  실행 방법:
echo    1. SlackUpdater.exe 를 backup/ 과 같은 곳에 두거나 어디서든 실행
echo    2. 백업 폴더와 DB 파일 경로 확인 후 "업데이트 시작" 클릭
echo =============================================
echo.
pause
