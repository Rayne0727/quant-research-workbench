@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Missing project interpreter: .venv\Scripts\python.exe
    exit /b 1
)

echo [1/5] Running Ruff lint...
".venv\Scripts\python.exe" -m ruff check app.py src tests
if errorlevel 1 exit /b 1

echo [2/5] Checking Ruff formatting...
".venv\Scripts\python.exe" -m ruff format --check app.py src tests
if errorlevel 1 exit /b 1

echo [3/5] Running 13-module strict static typing...
".venv\Scripts\python.exe" -m mypy ^
  src/performance.py ^
  src/adapters.py ^
  src/field_detection.py ^
  src/field_mapping.py ^
  src/standardization.py ^
  src/analysis_bridge.py ^
  src/limits.py ^
  src/data_loader.py ^
  src/file_import.py ^
  src/reference_files.py ^
  src/comparison.py ^
  src/reporting.py ^
  src/templates.py ^
  --strict ^
  --show-error-codes
if errorlevel 1 exit /b 1

echo [4/5] Running pytest with branch coverage...
".venv\Scripts\python.exe" -m pytest --cov=src --cov-branch --cov-report=term-missing
if errorlevel 1 exit /b 1

echo [5/5] Checking installed dependencies...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1

echo Engineering quality gate passed.
exit /b 0
