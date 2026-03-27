@echo off
cd ..
set PYTHONPATH=%PYTHONPATH%;%CD%
pytest tests/test_intensive_inheritance.py -v
pause
