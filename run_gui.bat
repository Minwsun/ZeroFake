@echo off
chcp 65001 >nul
echo ZeroFake
cd /d "%~dp0"
python gui/main_gui.py
pause

