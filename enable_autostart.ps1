param()

# 在用户启动文件夹创建“小智音乐MCP”快捷方式，实现登录时自动启动桥接。
$root = $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup '小智音乐MCP.lnk'
$ps1 = Join-Path $root 'start_bridge_hidden.ps1'

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = 'powershell.exe'
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`""
$s.WorkingDirectory = $root
$s.WindowStyle = 7
$s.Description = '小智AI 免费音乐 MCP 桥接（登录时自动启动）'
$s.Save()

if (Test-Path -LiteralPath $lnk) {
    Write-Output "[OK] 开机自启已启用: $lnk"
} else {
    Write-Error "创建快捷方式失败"
    exit 1
}
