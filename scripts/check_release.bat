@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Missing project interpreter: .venv\Scripts\python.exe
    exit /b 1
)

for %%F in (
    requirements.txt
    requirements-dev.txt
    .github\workflows\ci.yml
    docs\DEPLOYMENT.md
    docs\SECURITY_AND_PRIVACY.md
) do (
    if not exist "%%F" (
        echo Missing release file: %%F
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "from src.config import APP_VERSION; print('APP_VERSION=' + APP_VERSION)"
if errorlevel 1 exit /b 1

echo [1/3] Running pytest...
".venv\Scripts\python.exe" -m pytest
if errorlevel 1 (
    echo Pytest failed. Release check stopped.
    exit /b 1
)

echo [2/3] Compiling Python files...
".venv\Scripts\python.exe" -m compileall app.py src tests
if errorlevel 1 (
    echo Python compilation failed. Release check stopped.
    exit /b 1
)

echo [3/3] Checking Git worktree...
git status --short
set "WORKTREE_DIRTY="
for /f "delims=" %%S in ('git status --porcelain') do set "WORKTREE_DIRTY=1"
if defined WORKTREE_DIRTY (
    echo WARNING: Git worktree is not clean.
    exit /b 1
)

".venv\Scripts\python.exe" -c "from src.config import APP_VERSION; print('v' + APP_VERSION + ' \u672c\u5730\u53d1\u5e03\u68c0\u67e5\u901a\u8fc7\u3002')"
exit /b 0
