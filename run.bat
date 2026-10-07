@echo off
REM Run InputGlow from source (first time: installs what it needs)
python -m pip install --require-hashes -r requirements.txt --timeout 60
python app.py
pause
