@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Missing project interpreter: .venv\Scripts\python.exe
    exit /b 1
)

echo [1/4] Running Ruff lint...
".venv\Scripts\python.exe" -m ruff check app.py src tests
if errorlevel 1 exit /b 1

echo [2/4] Checking Ruff formatting...
".venv\Scripts\python.exe" -m ruff format --check app.py src tests
if errorlevel 1 exit /b 1

echo [3/4] Running pytest with branch coverage...
".venv\Scripts\python.exe" -m pytest --cov=src --cov-branch --cov-report=term-missing
if errorlevel 1 exit /b 1

echo [4/4] Checking installed dependencies...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1

echo Engineering quality gate passed.
exit /b 0
