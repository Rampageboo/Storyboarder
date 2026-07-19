@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  >&2 echo Storyboarder MCP needs the project virtual environment. Run Storyboarder once to create it.
  exit /b 1
)
".venv\Scripts\python.exe" -m storyboard_tool.mcp_server --session-base "%CD%"
