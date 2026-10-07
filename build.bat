@echo off
REM Build a single InputGlow.exe in the dist folder
python -m pip install -r requirements.txt pyinstaller --quiet
python -m PyInstaller --onefile --name InputGlow --add-data "web;web" app.py
echo.
echo Done! Your app is in the dist folder.
pause
