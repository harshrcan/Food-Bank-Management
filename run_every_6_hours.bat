@echo off
REM Optional: runs the AI check every 6 hours even when the web app is closed.
REM Run this file once as Administrator from the project folder.
schtasks /Create /TN "FoodBank AI Alerts" /SC HOURLY /MO 6 /F ^
  /TR "cmd /c cd /d \"%~dp0\" && python ai_engine.py >> ai_engine.log 2>&1"
echo Done. Check it in Task Scheduler under "FoodBank AI Alerts".
pause
