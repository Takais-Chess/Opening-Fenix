@echo off
cd /d "%~dp0"
set PYTHONPATH=.
".venv\Scripts\python.exe" main.py
