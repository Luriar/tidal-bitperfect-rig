@echo off
rem EqAPO reload: point config.txt at THIS folder's master (location-independent)
echo Include: %~dp0eqapo_master.txt> "C:\Program Files\EqualizerAPO\config\config.txt"
