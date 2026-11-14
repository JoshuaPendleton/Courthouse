@echo off
setlocal
cd /d "%~dp0"
rem GPU offload (needs llama-cpp-python built with Vulkan). -1 = all layers on GPU, 0 = CPU only.
if not defined COURTHOUSE_GPU_LAYERS set "COURTHOUSE_GPU_LAYERS=-1"
rem Vulkan device 0 = AMD Radeon RX 7900 XTX (skip the integrated GPU).
if not defined GGML_VK_VISIBLE_DEVICES set "GGML_VK_VISIBLE_DEVICES=0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" server.py
) else (
  echo No .venv found. Run install_dependencies_windows.bat first.
  py -3 server.py
)
if errorlevel 1 pause
endlocal
