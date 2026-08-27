@echo off
rem Register boot autostart: copies the vbs (hidden launcher) into shell:startup
copy /Y "%~dp0camilla_autostart.vbs" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\camilla_autostart.vbs"
echo done - supervisor will start hidden at every logon
pause
