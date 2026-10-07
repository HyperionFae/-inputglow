@echo off
REM Run InputGlow from source (first time: installs what it needs)
python -m pip install -r requirements.txt --quiet
python app.py
pause
