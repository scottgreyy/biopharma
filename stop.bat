@echo off
REM Asset Management Assistant - stop all services (Windows)
echo [stop] Stopping all Asset Management Assistant services...
taskkill /FI "WINDOWTITLE eq AMA_ReAct*"      /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AMA_Supervisor*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AMA_Router*"     /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AMA_Streamlit*"  /T /F >nul 2>&1
echo [stop] Done. All services stopped.
timeout /t 2 /nobreak >nul
