@echo off
copy /Y "%~dp0music_mobius.yml" "%~dp0config_template.yml" > nul
taskkill /F /IM camilladsp.exe > nul 2>&1
