@echo off
cd /d "%~dp0"
py -3 validate_template.py > validate_console.txt 2>&1
