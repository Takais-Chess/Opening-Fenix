@echo off
echo ==========================================
echo      Opening Fenix - Build Script
echo ==========================================
echo.
echo Usage:
echo   build_executable.bat             - Build BOTH installers (Private + Public)
echo   build_executable.bat public      - Build PUBLIC installer only
echo   build_executable.bat private     - Build PRIVATE installer only
echo.

if /I "%1"=="public" (
    python scripts/build_installer.py --public-only
) else if /I "%1"=="private" (
    python scripts/build_installer.py --private-only
) else (
    python scripts/build_installer.py
)

pause
