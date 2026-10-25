param()

# 以隐藏窗口方式后台启动小智音乐 MCP 桥接，日志写入 logs/ 目录。
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    Write-Error "未找到 $py，请先运行 setup.bat"
    exit 1
}

# 避免重复启动：存在同名进程则直接退出
$existing = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith((Join-Path $root ".venv"), [System.StringComparison]::OrdinalIgnoreCase) -and $_.StartTime -gt (Get-Date).AddMinutes(-1) }
if ($existing) {
    Write-Output "桥接已在运行，跳过启动。"
    exit 0
}

$out = Join-Path $logDir "bridge.out.log"
$err = Join-Path $logDir "bridge.err.log"
Start-Process -FilePath $py `
    -ArgumentList "bridge.py" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err
Write-Output "小智音乐 MCP 桥接已后台启动。日志: $err"
