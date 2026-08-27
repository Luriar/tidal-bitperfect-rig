@echo off
wmic process where "commandline like '%%supervisor.py%%'" call terminate > nul 2>&1
taskkill /F /IM camilladsp.exe > nul 2>&1
