$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
conda run -n Tools python scripts\build.py
if ($LASTEXITCODE -ne 0) { throw '构建失败' }
