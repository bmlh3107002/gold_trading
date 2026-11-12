<#
GW-06: gỡ MT5 Gateway tự chạy (Task Scheduler) và dừng Gateway đang chạy nền.
Cách dùng: powershell -ExecutionPolicy Bypass -File scripts\go-tu-chay.ps1
#>
$ErrorActionPreference = "Stop"
$TaskName = "GoldTrading MT5 Gateway"
$t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $t) { Write-Host "Chưa cài tự chạy ('$TaskName' không có)."; exit 0 }
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "ĐÃ GỠ: Gateway không còn tự chạy. Nếu còn tiến trình python của Gateway, mở Task Manager"
Write-Host "và kết thúc 'python' / 'uv' (hoặc khởi động lại máy)."
