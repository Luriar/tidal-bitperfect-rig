@echo off
copy /Y "%~dp0music_af140.yml" "%~dp0config_template.yml" > nul
taskkill /F /IM camilladsp.exe > nul 2>&1
