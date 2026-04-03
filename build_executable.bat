@echo off
echo ==========================================
echo      Opening Fenix - Build Script
echo ==========================================
echo.

echo 1. Installing requirements...
call .venv\Scripts\activate
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install requirements. Please check your internet connection or .venv setup.
    pause
    exit /b %errorlevel%
)

echo.
echo 2. Installing/Updating PyInstaller...
pip install pyinstaller
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b %errorlevel%
)

echo.
echo 2. Cleaning up previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist_backup" rmdir /s /q "dist_backup"
if exist "dist\Opening Fenix" (
    echo Preserving user data in dist\Opening Fenix...
    if not exist "dist_backup" mkdir "dist_backup"
    if exist "dist\Opening Fenix\profiles" move "dist\Opening Fenix\profiles" "dist_backup\"
    if exist "dist\Opening Fenix\repertoires" move "dist\Opening Fenix\repertoires" "dist_backup\"
    if exist "dist\Opening Fenix\config.json" move "dist\Opening Fenix\config.json" "dist_backup\"
    rmdir /s /q "dist"
) else (
    if exist "dist" rmdir /s /q "dist"
)

echo.
echo 3. Building the executable...
echo This may take a minute...
pyinstaller --noconfirm "Opening Fenix.spec"

if %errorlevel% neq 0 (
    echo.
    echo Build FAILED!
    # Restore user data on failure
    if exist "dist_backup" (
        if not exist "dist\Opening Fenix" mkdir "dist\Opening Fenix"
        if exist "dist_backup\profiles" move "dist_backup\profiles" "dist\Opening Fenix\"
        if exist "dist_backup\repertoires" move "dist_backup\repertoires" "dist\Opening Fenix\"
        if exist "dist_backup\config.json" move "dist_backup\config.json" "dist\Opening Fenix\"
        rmdir /s /q "dist_backup"
    )
    pause
    exit /b %errorlevel%
)

echo.
echo 4. Restoring user data and copying new Repertoires...
if exist "dist_backup" (
    if exist "dist_backup\profiles" move "dist_backup\profiles" "dist\Opening Fenix\"
    if exist "dist_backup\repertoires" move "dist_backup\repertoires" "dist\Opening Fenix\"
    if exist "dist_backup\config.json" move "dist_backup\config.json" "dist\Opening Fenix\"
    rmdir /s /q "dist_backup"
)

if not exist "dist\Opening Fenix\repertoires" mkdir "dist\Opening Fenix\repertoires"
xcopy /D /Y "repertoires\*.db" "dist\Opening Fenix\repertoires\"
xcopy /D /Y "*.md" "dist\Opening Fenix\"

echo.
echo ==========================================
echo           BUILD SUCCESSFUL!
echo ==========================================
echo.
echo Your program is ready in the "dist\Opening Fenix" folder.
echo.
echo To share it:
echo 1. Go to the "dist" folder.
echo 2. Right-click the "Opening Fenix" folder.
echo 3. Select "Send to" -> "Compressed (zipped) folder".
echo 4. Send the zip file to your friends!
echo.
pause
