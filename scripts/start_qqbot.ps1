# 启动 QQ Agent（需 NapCat WS ws://127.0.0.1:3001）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "Working dir: $(Get-Location)"
python -m agent
