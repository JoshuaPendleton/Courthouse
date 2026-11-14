@echo off
rem Courthouse dependency setup for Windows.
rem Builds llama-cpp-python with Vulkan GPU support (AMD, NVIDIA and Intel GPUs) when possible,
rem otherwise installs the prebuilt CPU wheel. Set COURTHOUSE_CPU_ONLY=1 to skip the GPU build.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto venv_ready
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.10+ from python.org.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto fail
:venv_ready
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto fail

if "%COURTHOUSE_CPU_ONLY%"=="1" (
  echo COURTHOUSE_CPU_ONLY=1 set: installing the CPU build.
  goto cpu
)

rem ---- Already a GPU build? Then nothing to rebuild. ----
"%PY%" -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" >nul 2>nul
if not errorlevel 1 (
  echo llama-cpp-python with GPU support is already installed.
  goto verify
)

rem ---- Find the Vulkan SDK ----
if defined VULKAN_SDK if exist "%VULKAN_SDK%\Bin" goto have_sdk
set "VULKAN_SDK="
if exist "C:\VulkanSDK" for /f "delims=" %%D in ('dir /b /ad /o:n "C:\VulkanSDK" 2^>nul') do set "VULKAN_SDK=C:\VulkanSDK\%%D"
if defined VULKAN_SDK goto have_sdk
echo.
echo The Vulkan SDK is needed to build GPU support and was not found.
where winget >nul 2>nul
if errorlevel 1 goto no_sdk
choice /c YN /m "Install the Vulkan SDK now with winget (admin prompt expected)"
if errorlevel 2 goto no_sdk
winget install --id KhronosGroup.VulkanSDK -e --accept-package-agreements --accept-source-agreements
if exist "C:\VulkanSDK" for /f "delims=" %%D in ('dir /b /ad /o:n "C:\VulkanSDK" 2^>nul') do set "VULKAN_SDK=C:\VulkanSDK\%%D"
if defined VULKAN_SDK goto have_sdk
:no_sdk
echo No Vulkan SDK: falling back to the CPU build. Install it from https://vulkan.lunarg.com and re-run for GPU support.
goto cpu

:have_sdk
echo Using Vulkan SDK: %VULKAN_SDK%

rem ---- The native build needs the MSVC C++ compiler ----
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto no_msvc
set "VSPATH="
for /f "usebackq delims=" %%P in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%P"
if defined VSPATH goto build
:no_msvc
echo Visual Studio C++ build tools not found ("Desktop development with C++" workload).
echo Falling back to the CPU build. Install the build tools and re-run for GPU support.
goto cpu

:build
echo Building llama-cpp-python with Vulkan GPU support. This takes several minutes...
set "PATH=%VULKAN_SDK%\Bin;%PATH%"
set "CMAKE_ARGS=-DGGML_VULKAN=on"
set "FORCE_CMAKE=1"
rem A short temp path avoids Windows' 260-character limit on the deeply nested llama.cpp sources.
set "BUILD_TMP=%SystemDrive%\lcb"
if not exist "%BUILD_TMP%" mkdir "%BUILD_TMP%"
set "TMP=%BUILD_TMP%"
set "TEMP=%BUILD_TMP%"
"%PY%" -m pip install --force-reinstall --no-cache-dir --no-binary llama-cpp-python -r requirements-inference.txt
if errorlevel 1 (
  echo.
  echo GPU build failed; see the errors above. Falling back to the CPU build.
  goto cpu
)
rmdir /s /q "%BUILD_TMP%" 2>nul
goto verify

:cpu
"%PY%" -m pip install --force-reinstall --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements-inference.txt
if errorlevel 1 goto fail

:verify
"%PY%" -c "from llama_cpp import Llama, StoppingCriteriaList"
if errorlevel 1 goto fail
"%PY%" -c "import llama_cpp; print('GPU offload: ' + ('ENABLED - run_windows.bat puts all layers on the GPU' if llama_cpp.llama_supports_gpu_offload() else 'not available - models will run on the CPU'))"
echo Dependencies installed. Start run_windows.bat.
pause
exit /b 0

:fail
echo Setup failed. Review the pip or import error above.
if exist "%PY%" "%PY%" -c "import sys, platform; print(sys.version, platform.machine(), platform.architecture()[0])"
echo If pip reports no matching distribution, check your Python version and architecture against the CPU wheels.
pause
exit /b 1
