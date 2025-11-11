@echo off
chcp 65001 >nul
echo Starting Zephyr Fact Checker GUI...
cd /d "%~dp0"
python gui/main_gui.py
pause

