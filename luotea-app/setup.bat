@echo off
REM Luotea Reliability Risk Engine — Windows setup + run
REM Requires Python 3.11+: https://www.python.org/downloads/
REM Run this from the luotea-app folder.

set PYTHONPATH=.

REM Find Python 3.11+
for %%p in (python3.13 python3.12 python3.11 python3 python) do (
    %%p -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" 2>nul
    if not errorlevel 1 (
        set PY=%%p
        goto :found
    )
)
echo ERROR: Python 3.11+ not found. Download from https://www.python.org/downloads/
exit /b 1

:found
echo Using %PY%

REM Create venv if needed
if not exist .venv\Scripts\python.exe (
    %PY% -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip -q
    .venv\Scripts\python -m pip install -r requirements.txt -q
    echo Venv ready.
)

REM Verify Gold data
.venv\Scripts\python -c "from pathlib import Path; p=Path('../luotea-pipeline/data/gold/site_daily_signals/site_daily_signals.parquet'); import sys; sys.exit(0) if p.exists() else (print('MISSING Gold parquet'), sys.exit(1))"
if errorlevel 1 exit /b 1
echo Gold data present.

REM Train, predict, test
.venv\Scripts\python -m src.models.train_sla       || exit /b 1
.venv\Scripts\python -m src.demo.build_demo_artifacts || exit /b 1
.venv\Scripts\python -m pytest tests\ -q           || exit /b 1

REM Launch app
echo.
echo Opening demo at http://localhost:8501
.venv\Scripts\python -m streamlit run src\demo\app.py
