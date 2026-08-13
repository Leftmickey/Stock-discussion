# 在 Windows 工作排程器建立每日更新工作。
#
# 用法（需系統管理員權限的 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File scripts\setup_schedule.ps1
#
# 移除排程：
#   Unregister-ScheduledTask -TaskName "台股熱度追蹤器每日更新" -Confirm:$false

param(
    # 台股 13:30 收盤，交易所盤後資料稍晚才齊，預設排在 15:30。
    [string]$Time = "15:30",
    [string]$TaskName = "台股熱度追蹤器每日更新"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BatchFile = Join-Path $ProjectRoot "scripts\run_daily.bat"

if (-not (Test-Path $BatchFile)) {
    Write-Error "找不到 $BatchFile"
    exit 1
}

Write-Host "專案路徑：$ProjectRoot"
Write-Host "執行時間：每個工作日 $Time"

$action = New-ScheduledTaskAction -Execute $BatchFile -WorkingDirectory $ProjectRoot

# 只在平日執行：假日沒有交易，PTT 討論量也極低。
$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "同名排程已存在，先移除舊的。"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "每日收盤後更新台股討論熱度與情緒資料" | Out-Null

Write-Host ""
Write-Host "排程建立完成。"
Write-Host "立即測試執行：Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "檢視執行狀態：Get-ScheduledTaskInfo -TaskName `"$TaskName`""
