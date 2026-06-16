@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\desktop.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "main.py" (
    echo [%DATE% %TIME%] Cannot find main.py in %CD%.>>"%LOG_FILE%"
    exit /b 1
)

rem Recreate the venv if it is missing OR broken (e.g. its base interpreter was
rem removed/moved). Checking only "not exist python.exe" misses a broken venv
rem whose stub exe is present but fails to launch — that silently fails here.
set "VENV_BROKEN="
if not exist "%VENV_DIR%\Scripts\python.exe" (
    set "VENV_BROKEN=1"
) else (
    "%VENV_DIR%\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 set "VENV_BROKEN=1"
)

if defined VENV_BROKEN (
    echo [%DATE% %TIME%] Creating/recreating virtual environment>>"%LOG_FILE%"
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" >>"%LOG_FILE%" 2>&1
    py -3 -m venv "%VENV_DIR%" >>"%LOG_FILE%" 2>&1
    if not exist "%VENV_DIR%\Scripts\python.exe" python -m venv "%VENV_DIR%" >>"%LOG_FILE%" 2>&1
)

call "%VENV_DIR%\Scripts\activate.bat" >>"%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1

python -c "import fastapi, uvicorn, webview" >nul 2>nul
if errorlevel 1 (
    python -m pip install -r "requirements.txt" >>"%LOG_FILE%" 2>&1
)

echo [%DATE% %TIME%] Starting Storyboard Tool ^(silent^)>>"%LOG_FILE%"
"%VENV_DIR%\Scripts\pythonw.exe" main.py %* >>"%LOG_FILE%" 2>&1
set "APP_EXIT_CODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] Exit code %APP_EXIT_CODE%>>"%LOG_FILE%"

exit /b %APP_EXIT_CODE%
