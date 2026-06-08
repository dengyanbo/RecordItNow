@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   RIN - Record It Now  one-click installer
echo ============================================================
echo.

set "BUNDLE_DIR=%~dp0bundle"
if not exist "%BUNDLE_DIR%\RIN.exe" (
    echo [ERROR] bundle\RIN.exe not found.
    echo.
    echo Did the zip extract correctly?
    echo Expected file: %BUNDLE_DIR%\RIN.exe
    echo.
    echo Open the extracted folder in File Explorer and confirm
    echo that "bundle" is a subdirectory next to this Install.bat.
    echo.
    pause
    exit /b 1
)

set "PS_EXE=powershell.exe"
where pwsh.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 set "PS_EXE=pwsh.exe"

echo Using %PS_EXE% to run install.ps1 ...
echo.
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -FromBundle "%BUNDLE_DIR%" -Force %*
set "PS_RC=%ERRORLEVEL%"

echo.
if not "%PS_RC%"=="0" (
    echo ============================================================
    echo   Installation FAILED with exit code %PS_RC%
    echo ============================================================
    echo Please copy the messages above and open an issue at:
    echo   https://github.com/dengyanbo/RecordItNow/issues
    echo.
    pause
    exit /b %PS_RC%
)

echo ============================================================
echo   Installation complete
echo ============================================================
echo Search "RIN" in the Start Menu to launch the app.
echo Data and logs live in %%LOCALAPPDATA%%\RIN.
echo.
pause
exit /b 0