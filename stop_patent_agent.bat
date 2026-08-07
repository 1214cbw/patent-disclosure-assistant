@echo off
setlocal
cd /d "%~dp0"
set "PATENT_AGENT_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PATENT_AGENT_PY%" set "PATENT_AGENT_PY=python"
"%PATENT_AGENT_PY%" scripts\stop_server.py
if errorlevel 1 pause
endlocal
