<#
GW-06: cài MT5 Gateway TỰ CHẠY khi đăng nhập Windows (Task Scheduler), chạy ẩn, tự chạy lại khi
dừng vì lỗi. Gateway chỉ đọc MT5, không đặt lệnh.

Vì sao không dùng "Windows Service": service chạy ở phiên hệ thống, không nói chuyện được với MT5
đang mở trong phiên đăng nhập của bạn. Task Scheduler chạy ngay trong phiên của bạn.

Cách dùng (mở PowerShell trong thư mục mt5_gateway):
  Một MT5 (gateway.env):            powershell -ExecutionPolicy Bypass -File scripts\cai-tu-chay.ps1
  Nhiều MT5 (thư mục terminals):    powershell -ExecutionPolicy Bypass -File scripts\cai-tu-chay.ps1 -NhieuMT5
Gỡ:                                 powershell -ExecutionPolicy Bypass -File scripts\go-tu-chay.ps1
Log: thư mục mt5_gateway\logs
#>
param([switch]$NhieuMT5)
$ErrorActionPreference = "Stop"
$TaskName = "GoldTrading MT5 Gateway"
$Dir = Split-Path -Parent $PSScriptRoot  # thư mục mt5_gateway

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { throw "Không tìm thấy uv. Làm Bước 5 trong README (cài uv) rồi chạy lại." }

if ($NhieuMT5) {
    if (-not (Test-Path (Join-Path $Dir "terminals"))) { throw "Chưa có thư mục terminals trong $Dir" }
    $GwArgs = "run mt5-gateway run-all --log-dir logs"
    $Check = "check-all"
} else {
    if (-not (Test-Path (Join-Path $Dir "gateway.env"))) { throw "Chưa có gateway.env trong $Dir" }
    $GwArgs = "run mt5-gateway run --log-file logs\gateway.log"
    $Check = "check"
}

Write-Host "Kiểm tra trước khi cài (uv run mt5-gateway $Check)..."
Push-Location $Dir
try {
    & $uv run mt5-gateway $Check
    if ($LASTEXITCODE -ne 0) { throw "Kiểm tra CHƯA ĐẠT: sửa các mục LỖI ở trên rồi chạy lại script này." }
} finally { Pop-Location }

# Chạy ẩn (cửa sổ PowerShell ẩn) trong thư mục mt5_gateway.
$Cmd = "& '" + $uv.Replace("'", "''") + "' " + $GwArgs
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"" + $Cmd + "`"") `
    -WorkingDirectory $Dir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Trigger.Delay = "PT1M"  # chờ 1 phút sau đăng nhập cho MT5 + Docker khởi động
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description "MT5 Gateway (chỉ đọc) — Gold Trading" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "ĐÃ CÀI: '$TaskName' tự chạy mỗi lần bạn đăng nhập Windows (sau 1 phút), và vừa được chạy."
Write-Host "Log: $Dir\logs  (mở bằng Notepad để xem)."
Write-Host "Lưu ý: đặt máy KHÔNG ngủ (Settings → System → Power) và để MT5 tự mở khi đăng nhập."
