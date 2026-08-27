@echo off
rem EqAPO life check: volume drops -25dB if EqAPO is active on Out 1-2
echo Preamp: -25 dB> "%~dp0current_m4.txt"
call "%~dp0_apply.bat"
