@echo off
cd /d "%~dp0"
py -3 supervisor.py --list > devices_console.txt 2>&1
