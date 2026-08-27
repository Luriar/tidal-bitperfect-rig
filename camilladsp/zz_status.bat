@echo off
cd /d "%~dp0"
py -3 tidal_status.py > nul 2>&1
