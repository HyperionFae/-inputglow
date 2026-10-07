@echo off
REM Build a single InputGlow.exe in the dist folder
python -m pip install --require-hashes -r requirements.txt --timeout 60
python -m PyInstaller --onefile --name InputGlow --add-data "web;web" app.py
echo.
echo Done! Your app is in the dist folder.
pause
