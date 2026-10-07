@echo off
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /Y "%~dp0camilla_autostart.vbs" "%STARTUP%\camilla_autostart.vbs" >nul

if exist "C:\EQ\light-host-autostart.vbs" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Light Host.lnk')); $s.TargetPath=(Join-Path $env:WINDIR 'System32\wscript.exe'); $s.Arguments=([char]34+'C:\EQ\light-host-autostart.vbs'+[char]34); $s.WorkingDirectory='C:\EQ'; $s.Save()"
)

echo Autostart installed: CamillaDSP supervisor + Light Host launcher.
echo Re-logon or reboot is enough; no reboot is performed by this script.
pause
