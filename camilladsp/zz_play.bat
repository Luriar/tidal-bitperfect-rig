@echo off
cd /d "%~dp0"
py -3 tidal_ctl.py play > tidal_ctl.log 2>&1
