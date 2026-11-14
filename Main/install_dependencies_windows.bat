@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.10+ from python.org.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements-inference.txt
if errorlevel 1 goto fail
echo Dependencies installed. Add agent1.gguf, agent2.gguf and agent3.gguf to models\agents.
pause
exit /b 0
:fail
echo Setup failed. See README.md for native build requirements.
pause
exit /b 1
