@echo off
echo ============================================
echo  Telemetry Analysis Platform - Build Script
echo ============================================
echo.

echo [1/2] Building executable with PyInstaller...
pyinstaller telemetry_tool.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed!
    pause
    exit /b 1
)

echo.
echo [2/2] Building installer with NSIS...
if exist "C:\Program Files (x86)\NSIS\makensis.exe" (
    "C:\Program Files (x86)\NSIS\makensis.exe" installer\telemetry_installer.nsi
) else if exist "C:\Program Files\NSIS\makensis.exe" (
    "C:\Program Files\NSIS\makensis.exe" installer\telemetry_installer.nsi
) else (
    echo WARNING: NSIS not found. Installer not built.
    echo Install NSIS from https://nsis.sourceforge.io/
    echo The executable is ready in dist\telemetry_tool\
)

echo.
echo Build complete!
if exist dist\TelemetryAnalysis_Setup.exe (
    echo Installer: dist\TelemetryAnalysis_Setup.exe
) else (
    echo Executable: dist\telemetry_tool\telemetry_tool.exe
)
pause
