@echo off
chcp 65001 >nul
setlocal
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
set "STREAMLIT_SERVER_SHOW_EMAIL_PROMPT=false"

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo 未找到项目虚拟环境，请先按照 README 完成安装。
    exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo 8501端口已被占用，请先在原Streamlit终端按Ctrl+C停止应用。
    exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501

endlocal
