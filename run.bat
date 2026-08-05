@echo off
REM Asset Management Assistant - Windows one-click launcher (uv-based)
setlocal
cd /d "%~dp0"

if not exist ".env" (
    echo [run] No .env file found. Copy .env.example to .env and set OLLAMA_API_KEY.
    pause
    exit /b 1
)

REM Seed the database on first run.
if not exist "data\assets.db" (
    echo [run] Seeding database for the first time...
    uv run python -m shared.db.init_db
    if errorlevel 1 (
        echo [run] Database seeding failed. See the error above.
        pause
        exit /b 1
    )
)

echo [run] Starting Backend 1 (ReAct) on port 8001...
start "AMA_ReAct"      cmd /k "cd /d ""%~dp0"" && uv run uvicorn backend_react.main:app --host 127.0.0.1 --port 8001"

echo [run] Starting Backend 2 (Supervisor) on port 8002...
start "AMA_Supervisor" cmd /k "cd /d ""%~dp0"" && uv run uvicorn backend_supervisor.main:app --host 127.0.0.1 --port 8002"

echo [run] Starting Backend 3 (Router) on port 8003...
start "AMA_Router"     cmd /k "cd /d ""%~dp0"" && uv run uvicorn backend_router.main:app --host 127.0.0.1 --port 8003"

echo [run] Starting Admin (Data Management) on port 8004...
start "AMA_Admin"      cmd /k "cd /d ""%~dp0"" && uv run uvicorn backend_admin.main:app --host 127.0.0.1 --port 8004"

echo [run] Waiting for backends to start...
timeout /t 8 /nobreak >nul

echo [run] Starting Streamlit UI on port 8501...
start "AMA_Streamlit"  cmd /k "cd /d ""%~dp0"" && uv run streamlit run streamlit_app/app.py --server.port 8501 --server.headless true"

echo [run] Waiting for Streamlit to be ready...
set /a _tries=0
:WAIT_STREAMLIT
timeout /t 2 /nobreak >nul
set /a _tries+=1
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8501); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    if %_tries% LSS 20 goto WAIT_STREAMLIT
)
start "" http://localhost:8501

echo.
echo ===================================================================
echo  All services launched in separate windows:
echo    UI:          http://localhost:8501
echo    ReAct:       http://localhost:8001/docs
echo    Supervisor:  http://localhost:8002/docs
echo    Router:      http://localhost:8003/docs
echo    Admin:       http://localhost:8004/docs
echo.
echo  To STOP everything: double-click stop.bat
echo ===================================================================
echo.
echo You can close THIS window now. The services keep running in theirs.
pause
endlocal
