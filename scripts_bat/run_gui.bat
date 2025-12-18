@echo off
chcp 65001 >nul
echo ZeroFake
REM Change to project root directory (parent of scripts_bat)
cd /d "%~dp0.."
python gui/main_gui.py
pause

