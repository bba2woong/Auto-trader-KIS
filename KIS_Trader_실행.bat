@echo off
cd /d "%~dp0"
echo KIS Auto Trader 시작 중...
.\venv\Scripts\streamlit run app.py
pause
