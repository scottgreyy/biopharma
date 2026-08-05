@echo off
REM Asset Management Assistant - stop all services (Windows), by port.
echo [stop] Stopping all Asset Management Assistant services...

for %%P in (8001 8002 8003 8004 8501) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P" ^| findstr "LISTENING"') do (
        echo   stopping process on port %%P (PID %%A)
        taskkill /PID %%A /T /F >nul 2>&1
    )
)

REM Also close any leftover service windows by title (belt and suspenders).
taskkill /FI "WINDOWTITLE eq AMA_*" /T /F >nul 2>&1

echo [stop] Done. All services stopped.
timeout /t 2 /nobreak >nul
