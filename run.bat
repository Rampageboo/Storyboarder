@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\desktop.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "main.py" (
    echo Cannot find main.py in %CD%.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating local virtual environment...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        python -m venv "%VENV_DIR%"
    )
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    "%VENV_DIR%\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 (
        echo Recreating broken virtual environment...
        rmdir /s /q "%VENV_DIR%"
        py -3 -m venv "%VENV_DIR%"
        if not exist "%VENV_DIR%\Scripts\python.exe" (
            echo Failed to recreate virtual environment.
            pause
            exit /b 1
        )
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

python -c "import fastapi, uvicorn, webview" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies ^(first run or missing packages^)...
    python -m pip install -r "requirements.txt"
    if errorlevel 1 (
        echo Failed to install requirements.txt.
        pause
        exit /b 1
    )
)

echo Starting Storyboard Tool desktop window...
echo Logs: %LOG_FILE%
echo.
echo [%DATE% %TIME%] Starting Storyboard Tool>>"%LOG_FILE%"
powershell -NoProfile -Command "python main.py %* 2>&1 | Tee-Object -FilePath '%LOG_FILE%' -Append"
set "APP_EXIT_CODE=%ERRORLEVEL%"

echo.
echo Storyboard Tool exited with code %APP_EXIT_CODE%.
pause
exit /b %APP_EXIT_CODE%
