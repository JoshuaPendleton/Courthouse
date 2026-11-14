@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" server.py
) else (
  echo No .venv found. Run install_dependencies_windows.bat first.
  py -3 server.py
)
if errorlevel 1 pause
endlocal
