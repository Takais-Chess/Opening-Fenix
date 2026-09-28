@echo off
echo ================================================================
echo   Opening Fenix - Multilingual Visual Inspection Suite (DE & EN)
echo ================================================================
echo.

python scripts\multilingual_visual_test.py --check-new --clean

if exist "Output\visual_review\index.html" (
    echo.
    echo Opening visual comparison report in your default browser...
    start "" "Output\visual_review\index.html"
)

echo.
pause
