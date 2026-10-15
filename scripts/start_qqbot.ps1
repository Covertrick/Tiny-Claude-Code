# 一键启动：自动补全 agent/.env → 拉起 NapCat → 启动 QQ Agent
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "Working dir: $(Get-Location)"
Write-Host "Bootstrapping NapCat + Agent ..."
$env:PYTHONUNBUFFERED = "1"
python -u -m agent
