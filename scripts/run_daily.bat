@echo off
REM 每日收盤後的增量更新。供 Windows 工作排程器呼叫。
REM
REM 排程建議設在 15:30 之後（台股 13:30 收盤，交易所盤後資料稍晚才更新）。
REM 建立排程請執行 scripts\setup_schedule.ps1。

setlocal

REM 切到專案根目錄，讓相對路徑與資料庫位置不受排程器工作目錄影響。
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [錯誤] 找不到虛擬環境 .venv，請先依 README 完成安裝。
    exit /b 1
)

echo ===============================================
echo  台股熱度追蹤器 - 每日更新
echo  %date% %time%
echo ===============================================

".venv\Scripts\python.exe" -m stockheat.cli daily
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% neq 0 (
    echo.
    echo [警告] 更新過程有步驟失敗，詳見 data\logs 下的日誌。
)

exit /b %EXITCODE%
