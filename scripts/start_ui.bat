@echo off
cd /d "%~dp0\.."
set GRAPHITI_ENABLED=0
echo.
echo Starting Project Synapse UI...
echo Keep this window OPEN while you use the browser.
echo.
echo When you see "Synapse API + UI", open:
echo   http://127.0.0.1:8787/
echo.
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data\sense.db
pause
