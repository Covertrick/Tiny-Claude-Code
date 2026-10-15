# NapCat WebUI 一键打开并自动填 Token
# 用法：powershell -File scripts/open_webui.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""

python -m agent.webui_login
if ($LASTEXITCODE -ne 0) {
    Write-Host "自动登录失败。可手动打开 http://127.0.0.1:6099/webui/web_login ，Token 见 agent/.env 的 NAPCAT_WEBUI_TOKEN"
    exit $LASTEXITCODE
}
