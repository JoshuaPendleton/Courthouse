@echo off
cd /d "%~dp0"
echo.
echo ===============================================
echo   AEGIS LAB - AI MODEL SECURITY TESTING
 echo ===============================================
echo.
echo Open http://127.0.0.1:8050 in your browser.
echo Keep this window running while using the site.
echo.
py -3 server.py
if errorlevel 1 (
    echo Trying python instead of py...
    python server.py
)
pause
