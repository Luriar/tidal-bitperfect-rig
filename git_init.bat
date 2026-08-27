@echo off
cd /d "%~dp0"
del stage.log 2>nul
git init > git_setup.log 2>&1
git add -A >> git_setup.log 2>&1
git commit -m "Initial commit: TIDAL bit-perfect auto-rate chain + EQ system" >> git_setup.log 2>&1
git log --oneline -1 >> git_setup.log 2>&1
