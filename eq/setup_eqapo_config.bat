@echo off
rem First-time wiring (usually NOT needed as admin - config dir is user-writable)
echo Include: %~dp0eqapo_master.txt> "C:\Program Files\EqualizerAPO\config\config.txt"
echo --- config.txt now contains: ---
type "C:\Program Files\EqualizerAPO\config\config.txt"
pause
