# Starts the HB LAN server (API + built SPA) by delegating to `hb serve`
# (backend/hb/serve.py): plain HTTP on 18800 (HB_HTTP_PORT in .env), bound on
# 0.0.0.0 so any device on the wifi can reach it with nothing to install. The
# firewall rule from ops/windows-lan.ps1 (Private profile + LocalSubnet) is what
# keeps it LAN-only.
#
# Invoked by the "HB API Server" scheduled task that ops/windows-lan.ps1 registers.
# --no-sync: a running pipeline holds .venv\Scripts\hb.exe, so a sync here could
# keep the server from starting; `make deploy-windows` syncs while it is stopped.

$ErrorActionPreference = "Stop"

$backend = (Resolve-Path (Join-Path $PSScriptRoot "..\backend")).Path

Set-Location $backend
$uv = (Get-Command uv).Source
& $uv run --no-sync hb serve
