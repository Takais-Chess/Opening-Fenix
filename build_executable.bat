@echo off
echo ==========================================
echo      Opening Fenix - Build Script
echo ==========================================
echo.

:: Check if Opening Fenix is currently running (either as EXE or via main.py)
set APP_RUNNING=0

:: Check for the compiled EXE
tasklist /FI "IMAGENAME eq Opening Fenix.exe" 2>NUL | find /I /N "Opening Fenix.exe">NUL
if "%ERRORLEVEL%"=="0" set APP_RUNNING=1

:: Check for the program running via python (main.py)
:: We use wmic to check the command line of running processes, but limit it to python to avoid wmic detecting itself
wmic process where "name like 'python%%' and CommandLine like '%%main.py%%'" get CommandLine 2>NUL | find /I "main.py" >NUL
if "%ERRORLEVEL%"=="0" set APP_RUNNING=1

if "%APP_RUNNING%"=="1" (
    echo [ERROR] Opening Fenix is currently running!
    echo Please close the program - EXE or main.py - before running the build script to prevent data corruption.
    pause
    exit /b 1
)

echo 1. Generating Timestamp for Backups...
for /f "delims=" %%a in ('wmic OS Get localdatetime ^| find "."') do set dt=%%a
set YYYY=%dt:~0,4%
set MM=%dt:~4,2%
set DD=%dt:~6,2%
set HH=%dt:~8,2%
set Min=%dt:~10,2%
set Sec=%dt:~12,2%
set TIMESTAMP=%YYYY%-%MM%-%DD%_%HH%-%Min%-%Sec%
set BACKUP_DIR=Backups\backup of repertoire and profile from %TIMESTAMP%

echo.
echo 2. Backing up current user data...
if not exist "%BACKUP_DIR%\project_data" mkdir "%BACKUP_DIR%\project_data"
if not exist "%BACKUP_DIR%\exe_data" mkdir "%BACKUP_DIR%\exe_data"

:: Backup Project Data
if exist "profiles" xcopy /E /I /H /Y "profiles\*" "%BACKUP_DIR%\project_data\profiles\" >nul
if exist "repertoires" xcopy /E /I /H /Y "repertoires\*" "%BACKUP_DIR%\project_data\repertoires\" >nul

:: Backup EXE Data
if exist "dist\Opening Fenix\profiles" xcopy /E /I /H /Y "dist\Opening Fenix\profiles\*" "%BACKUP_DIR%\exe_data\profiles\" >nul
if exist "dist\Opening Fenix\repertoires" xcopy /E /I /H /Y "dist\Opening Fenix\repertoires\*" "%BACKUP_DIR%\exe_data\repertoires\" >nul

echo.
echo 3. Syncing changes from EXE to Project Folder...
if exist "dist\Opening Fenix\profiles" xcopy /E /I /H /Y /D "dist\Opening Fenix\profiles\*" "profiles\" >nul
if exist "dist\Opening Fenix\repertoires" xcopy /E /I /H /Y /D "dist\Opening Fenix\repertoires\*" "repertoires\" >nul

echo.
echo 4. Installing requirements...
call .venv\Scripts\activate
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install requirements. Please check your internet connection or .venv setup.
    pause
    exit /b %errorlevel%
)

echo.
echo 5. Installing/Updating PyInstaller...
pip install pyinstaller
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b %errorlevel%
)

echo.
echo 6. Cleaning up previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist_backup" rmdir /s /q "dist_backup"
if exist "dist\Opening Fenix" (
    echo Preserving config.json in dist\Opening Fenix...
    if not exist "dist_backup" mkdir "dist_backup"
    if exist "dist\Opening Fenix\config.json" move "dist\Opening Fenix\config.json" "dist_backup\" >nul
)
if exist "dist" rmdir /s /q "dist"

echo.
echo 7. Building the executable...
echo This may take a minute...
pyinstaller --noconfirm "Opening Fenix.spec"

if %errorlevel% neq 0 (
    echo.
    echo Build FAILED!
    :: Restore user data on failure
    if exist "dist_backup" (
        if not exist "dist\Opening Fenix" mkdir "dist\Opening Fenix"
        if exist "dist_backup\config.json" move "dist_backup\config.json" "dist\Opening Fenix\" >nul
        rmdir /s /q "dist_backup"
    )
    pause
    exit /b %errorlevel%
)

echo.
echo 8. Restoring user data and copying new Repertoires...
if exist "dist_backup" (
    if not exist "dist\Opening Fenix" mkdir "dist\Opening Fenix"
    if exist "dist_backup\config.json" move "dist_backup\config.json" "dist\Opening Fenix\" >nul
    rmdir /s /q "dist_backup"
)

if not exist "dist\Opening Fenix\profiles" mkdir "dist\Opening Fenix\profiles"
xcopy /E /I /H /Y /D "profiles\*" "dist\Opening Fenix\profiles\" >nul

if not exist "dist\Opening Fenix\repertoires" mkdir "dist\Opening Fenix\repertoires"
xcopy /E /I /H /Y /D "repertoires\*" "dist\Opening Fenix\repertoires\" >nul

xcopy /D /Y "*.md" "dist\Opening Fenix\" >nul

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
