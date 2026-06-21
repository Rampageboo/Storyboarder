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

:: ── Generate per-launch token FIRST ───────────────────────────────────────────
set "LAUNCH_TOKEN="
for /f "delims=" %%G in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')" 2^>nul') do set "LAUNCH_TOKEN=%%G"
set "STORYBOARDER_LAUNCH_TOKEN=!LAUNCH_TOKEN!"

:: ── Start splash BEFORE any Python/venv work ──────────────────────────────────
:: The user sees feedback immediately, even on first run or broken environment.
set "SPLASH_SCRIPT=%~dp0scripts\launch-storyboarder-splash.ps1"
if exist "%SPLASH_SCRIPT%" (
    if "!LAUNCH_TOKEN!"=="" (
        start "" /b powershell -NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "%SPLASH_SCRIPT%"
    ) else (
        start "" /b powershell -NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "%SPLASH_SCRIPT%" -Token "!LAUNCH_TOKEN!"
    )
)

echo [%DATE% %TIME%] Launcher started (token: !LAUNCH_TOKEN!)>>"%LOG_FILE%"

:: ── Virtual environment setup ────────────────────────────────────────────────
call :WriteStatus "Preparing Python environment…"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating local virtual environment...
    echo [%DATE% %TIME%] Creating venv>>"%LOG_FILE%"
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 python -m venv "%VENV_DIR%"
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        call :MarkFailed "Failed to create Python virtual environment. Check logs/desktop.log for details."
        exit /b 1
    )
) else (
    "%VENV_DIR%\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 (
        echo Recreating broken virtual environment...
        echo [%DATE% %TIME%] Recreating broken venv>>"%LOG_FILE%"
        rmdir /s /q "%VENV_DIR%"
        py -3 -m venv "%VENV_DIR%"
        if not exist "%VENV_DIR%\Scripts\python.exe" (
            call :MarkFailed "Failed to recreate Python virtual environment. Check logs/desktop.log for details."
            exit /b 1
        )
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    call :MarkFailed "Failed to activate Python virtual environment. Check logs/desktop.log for details."
    exit /b 1
)

:: ── Dependency check ─────────────────────────────────────────────────────────
call :WriteStatus "Checking dependencies…"
python -c "import fastapi, uvicorn, webview" >nul 2>nul
if errorlevel 1 (
    call :WriteStatus "Installing dependencies…"
    echo Installing Python dependencies ^(first run or missing packages^)...
    echo [%DATE% %TIME%] Installing dependencies>>"%LOG_FILE%"
    python -m pip install -r "%REQ_FILE%"
    if errorlevel 1 (
        call :MarkFailed "Failed to install Python dependencies. Check logs/desktop.log for details."
        exit /b 1
    )
)

:: ── Launch Python application ─────────────────────────────────────────────────
call :WriteStatus "Starting Storyboarder…"
echo [%DATE% %TIME%] Starting Storyboarder>>"%LOG_FILE%"
python main.py %*
set "APP_EXIT_CODE=!ERRORLEVEL!"

if !APP_EXIT_CODE! neq 0 (
    call :MarkFailed "Storyboarder exited unexpectedly. Check logs/desktop.log for details."
    exit /b !APP_EXIT_CODE!
)

:: ── Clean up per-launch token files ──────────────────────────────────────────
if not "!LAUNCH_TOKEN!"=="" (
    del /f /q "%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.ready"  2>nul
    del /f /q "%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.status" 2>nul
    del /f /q "%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.failed" 2>nul
)

exit /b 0

:: ── Subroutines ──────────────────────────────────────────────────────────────

:WriteStatus
    if not "!LAUNCH_TOKEN!"=="" (
        >"%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.status" echo %~1 2>nul
    )
    exit /b 0

:MarkFailed
    if not "!LAUNCH_TOKEN!"=="" (
        >"%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.status" echo %~1 2>nul
        >"%TEMP%\storyboarder-launch-!LAUNCH_TOKEN!.failed" echo FAILED 2>nul
    )
    echo %~1
    echo [%DATE% %TIME%] FAILED: %~1>>"%LOG_FILE%"
    exit /b 0
