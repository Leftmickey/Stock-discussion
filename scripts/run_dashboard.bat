@echo off
REM 啟動熱度儀表板，瀏覽器會自動開啟。

setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [錯誤] 找不到虛擬環境 .venv，請先依 README 完成安裝。
    pause
    exit /b 1
)

echo 儀表板啟動中，瀏覽器會自動開啟 http://localhost:8501
echo 要停止請在這個視窗按 Ctrl+C。
echo.

".venv\Scripts\python.exe" -m streamlit run app\dashboard.py

pause
