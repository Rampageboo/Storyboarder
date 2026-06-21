@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\desktop.log"
set "REQ_FILE=requirements.lock.txt"
if not exist "%REQ_FILE%" set "REQ_FILE=requirements.txt"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "main.py" (
    echo Cannot find main.py in %CD%.
    pause
    exit /b 1
)

:: ── Virtual environment setup ────────────────────────────────────────────────
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating local virtual environment...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 python -m venv "%VENV_DIR%"
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

:: ── Dependency check ─────────────────────────────────────────────────────────
python -c "import fastapi, uvicorn, webview" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies ^(first run or missing packages^)...
    python -m pip install -r "%REQ_FILE%"
    if errorlevel 1 (
        echo Failed to install %REQ_FILE%.
        pause
        exit /b 1
    )
)

:: ── Generate unique per-launch token ─────────────────────────────────────────
:: Use PowerShell to create a UUID (no external tools needed).
set "LAUNCH_TOKEN="
for /f "delims=" %%G in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')" 2^>nul') do set "LAUNCH_TOKEN=%%G"

if "!LAUNCH_TOKEN!"=="" (
    echo Warning: could not generate launch token; splash will use timeout fallback.
)

set "STORYBOARDER_LAUNCH_TOKEN=!LAUNCH_TOKEN!"

:: ── Start splash before Python imports heavyweight modules ────────────────────
set "SPLASH_SCRIPT=%~dp0scripts\launch-storyboarder-splash.ps1"
if exist "%SPLASH_SCRIPT%" (
    if "!LAUNCH_TOKEN!"=="" (
        start "" /b powershell -NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "%SPLASH_SCRIPT%"
    ) else (
        start "" /b powershell -NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "%SPLASH_SCRIPT%" -Token "!LAUNCH_TOKEN!"
    )
)

:: ── Launch Python application ─────────────────────────────────────────────────
echo [%DATE% %TIME%] Starting Storyboarder (token: !LAUNCH_TOKEN!)>>"%LOG_FILE%"
python main.py %*
set "APP_EXIT_CODE=!ERRORLEVEL!"

:: ── Clean up any leftover per-launch token files ─────────────────────────────
if not "!LAUNCH_TOKEN!"=="" (
    del /f /q "%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.ready"  2>nul
    del /f /q "%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.status" 2>nul
)

exit /b !APP_EXIT_CODE!
