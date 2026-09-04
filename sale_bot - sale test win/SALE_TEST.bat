@echo off
setlocal
cd /d "%~dp0"
py -3.12 win_menu.py
if errorlevel 1 python win_menu.py
