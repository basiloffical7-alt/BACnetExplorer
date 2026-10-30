@echo off
cd /d "%~dp0"
python bacnet_simulator.py --port 47809
pause
