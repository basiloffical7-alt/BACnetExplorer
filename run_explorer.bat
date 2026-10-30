@echo off
cd /d "%~dp0"
python bacnet_explorer.py
if errorlevel 1 pause
