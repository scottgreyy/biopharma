@echo off
REM Asset Management Assistant - Windows one-click launcher
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [run] No virtual environment found at venv\
    echo       Create it: uv venv venv ^&^& venv\Scripts\activate ^&^& uv pip install -r requirements.txt
    pause
    exit /b 1
)

set "VENV_ACT=%~dp0venv\Scripts\activate.bat"

if not exist ".env" (
    echo [run] WARNING: no .env file found.
    echo       Copy .env.example to .env and set OLLAMA_API_KEY, then re-run.
    pause
    exit /b 1
)

if not exist "data\assets.db" (
    echo [run] Seeding database for the first time...
    call "%VENV_ACT%"
    python -m shared.db.init_db
    if errorlevel 1 (
        echo [run] Database seeding failed. See the error above.
        pause
        exit /b 1
    )
)

echo [run] Starting Backend 1 (ReAct) on port 8001...
start "AMA_ReAct"      cmd /k "call ""%VENV_ACT%"" && python -m uvicorn backend_react.main:app --host 127.0.0.1 --port 8001"

echo [run] Starting Backend 2 (Supervisor) on port 8002...
start "AMA_Supervisor" cmd /k "call ""%VENV_ACT%"" && python -m uvicorn backend_supervisor.main:app --host 127.0.0.1 --port 8002"

echo [run] Starting Backend 3 (Router) on port 8003...
start "AMA_Router"     cmd /k "call ""%VENV_ACT%"" && python -m uvicorn backend_router.main:app --host 127.0.0.1 --port 8003"

echo [run] Waiting for backends to start...
timeout /t 6 /nobreak >nul

echo [run] Starting Streamlit UI on port 8501...
start "AMA_Streamlit"  cmd /k "call ""%VENV_ACT%"" && python -m streamlit run streamlit_app/app.py --server.port 8501"

timeout /t 4 /nobreak >nul
start "" http://localhost:8501

echo.
echo ===================================================================
echo  All services launched in separate windows:
echo    UI:          http://localhost:8501   (browser opened)
echo    ReAct:       http://localhost:8001/docs
echo    Supervisor:  http://localhost:8002/docs
echo    Router:      http://localhost:8003/docs
echo.
echo  To STOP everything: double-click stop.bat
echo ===================================================================
echo.
echo You can close THIS window now. The services keep running in theirs.
pause
endlocal
