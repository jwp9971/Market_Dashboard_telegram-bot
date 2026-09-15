@echo off
REM Resolves paths from this file's own directory, so the repo can live
REM anywhere and on any machine.
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"
python src\main.py
pause
