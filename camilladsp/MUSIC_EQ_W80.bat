@echo off
copy /Y "%~dp0music_w80.yml" "%~dp0config_template.yml" > nul
taskkill /F /IM camilladsp.exe > nul 2>&1
