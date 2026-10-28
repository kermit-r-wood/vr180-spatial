@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.ps1 with Python 3.12 or newer first.
    pause
    exit /b 1
)
if "%~1"=="" (
    echo Drag a VR180 JPG or a folder onto this file.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" vr180_to_spatial.py %*
set "result=%errorlevel%"
echo.
echo Finished with exit code %result%. Results are in the output folder.
pause
exit /b %result%
