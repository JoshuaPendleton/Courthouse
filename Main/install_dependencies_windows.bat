@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.10+ from python.org.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements-inference.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "from llama_cpp import Llama, StoppingCriteriaList"
if errorlevel 1 goto fail
echo Dependencies installed. Start run_windows.bat.
pause
exit /b 0
:fail
echo Setup failed. Review the pip or import error above.
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -c "import sys, platform; print(sys.version, platform.machine(), platform.architecture()[0])"
echo If pip reports no matching distribution, check your Python version and architecture against the CPU wheels.
pause
exit /b 1
