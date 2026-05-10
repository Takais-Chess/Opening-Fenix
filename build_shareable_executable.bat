@echo off
set FENIX_SHARE_BUILD=1
echo ==========================================
echo      Opening Fenix - Public Build Script
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
echo 3. Cleaning up previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist\Opening Fenix Public" rmdir /s /q "dist\Opening Fenix Public"

echo.
echo 4. Building the executable...
echo This may take a minute...
pyinstaller --noconfirm "Opening Fenix.spec"

if %errorlevel% neq 0 (
    echo.
    echo Build FAILED!
    pause
    exit /b %errorlevel%
)

echo.
echo 5. Creating empty folders and copying documentation...
if not exist "dist\Opening Fenix Public\engines" mkdir "dist\Opening Fenix Public\engines"
if not exist "dist\Opening Fenix Public\repertoires" mkdir "dist\Opening Fenix Public\repertoires"
if not exist "dist\Opening Fenix Public\profiles" mkdir "dist\Opening Fenix Public\profiles"

:: Create a readme for the engines folder to help the user
echo Put your Stockfish engine or other UCI engines here. > "dist\Opening Fenix Public\engines\README_ENGINES.txt"

copy /y "README.md" "dist\Opening Fenix Public\" 2>nul
copy /y "CHANGELOG.md" "dist\Opening Fenix Public\" 2>nul
copy /y "QUICKSTART.md" "dist\Opening Fenix Public\" 2>nul

echo.
echo ==========================================
echo           PUBLIC BUILD SUCCESSFUL!
echo ==========================================
echo.
echo Your shareable program is ready in the "dist\Opening Fenix Public" folder.
echo.
echo This build:
echo - DOES NOT include your local engine executables.
echo - DOES NOT include your personal repertoires.
echo - DOES NOT include your personal profiles or config.
echo.
echo To share it:
echo 1. Go to the "dist" folder.
echo 2. Right-click the "Opening Fenix Public" folder.
echo 3. Select "Send to" -> "Compressed (zipped) folder".
echo 4. Send the zip file to your friends!
echo.
pause
