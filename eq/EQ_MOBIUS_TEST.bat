@echo off
rem EqAPO life check: volume drops -25dB if EqAPO is active on Mobius
echo Preamp: -25 dB> "%~dp0current_mobius.txt"
call "%~dp0_apply.bat"
