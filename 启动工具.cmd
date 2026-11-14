@echo off
cd /d "%~dp0"
if exist "%~dp0dist\V2rayNSplitGuard.exe" (
  start "" "%~dp0dist\V2rayNSplitGuard.exe"
  exit /b 0
)
if exist "%~dp0dist\V2rayNSplitGuard\V2rayNSplitGuard.exe" (
  start "" "%~dp0dist\V2rayNSplitGuard\V2rayNSplitGuard.exe"
) else (
  where conda >nul 2>nul
  if errorlevel 1 (
    echo Python environment not found. Install Conda Tools or use the packaged EXE.
    pause
    exit /b 1
  )
  call conda run --no-capture-output -n Tools pythonw.exe "%~dp0app.py"
)
