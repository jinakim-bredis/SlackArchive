@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo =============================================
echo  Slack DM Archiver — PyInstaller 빌드
echo =============================================
echo.

REM slackdump.exe가 상위 폴더에 있는지 확인
if not exist "..\slackdump.exe" (
    echo [오류] ..\slackdump.exe 를 찾을 수 없습니다.
    echo 프로젝트 루트에 slackdump.exe 가 있는지 확인하세요.
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
    --name SlackDMArchiver ^
    --clean ^
    archiver.py

if errorlevel 1 (
    echo.
    echo [오류] PyInstaller 빌드 실패
    pause
    exit /b 1
)

echo.
echo [3/3] 완료!
echo =============================================
echo  결과물: dist\SlackDMArchiver.exe
echo  이 파일을 Python 없는 PC로 복사하여 실행하세요.
echo =============================================
echo.
pause
