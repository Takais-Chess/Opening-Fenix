@echo off
echo ================================================================
echo   Opening Fenix - Multi-Display Visual Overflow Audit
echo ================================================================
echo.
echo Running automated audit across HD (768p), FHD Laptop (125%%), and FHD Desktop (100%%)...
echo.

python scripts\display_overflow_harness.py --html

if exist "Output\display_audit\index.html" (
    echo.
    echo Opening display overflow report in your default browser...
    start "" "Output\display_audit\index.html"
)

echo.
pause
