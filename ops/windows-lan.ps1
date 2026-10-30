# Exposes the HB server to the home LAN only (no public/internet traffic).
# Run as Administrator. Idempotent: safe to re-run any time (e.g. after a
# port change — it removes stale rules and re-registers the task).
#
# What it does:
#   1. Adds a Windows Firewall rule for TCP $port, doubly scoped:
#      - Profile Private  -> active only on networks marked as trusted/home
#      - RemoteAddress LocalSubnet -> accepts connections only from LAN IPs
#      The router's NAT is what blocks the internet side; never add a
#      port-forward/UPnP entry for this port on the router.
#   2. Warns if the current network profile is Public (rule would stay inert).
#   3. Registers an at-logon scheduled task that runs ops/serve.ps1 -> `hb serve`,
#      which serves the API + built SPA as plain HTTP on $port. Nothing here is
#      reachable off the LAN.

$ErrorActionPreference = "Stop"

$port = 18800  # outside the common dev range so 3000/5173/8000/8081 stay free

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Run this script from an elevated (Administrator) PowerShell."
}

$backend = (Resolve-Path (Join-Path $PSScriptRoot "..\backend")).Path
$serve = (Resolve-Path (Join-Path $PSScriptRoot "serve.ps1")).Path
$pwsh = (Get-Command powershell).Source

# --- 1. Firewall rule (remove it if present, re-create) ---
$ruleName = "HB LAN"
Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
    -Protocol TCP -LocalPort $port -Action Allow `
    -Profile Private -RemoteAddress LocalSubnet | Out-Null
Write-Host "firewall: '$ruleName' allows TCP $port from LocalSubnet on Private networks only"

# --- 2. Network profile check ---
$publicProfiles = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq "Public" }
foreach ($p in $publicProfiles) {
    Write-Warning ("network '{0}' (interface {1}) is categorized Public, so the firewall rule will not match it. " -f $p.Name, $p.InterfaceIndex)
    Write-Warning ("if this is your home network, mark it trusted with: Set-NetConnectionProfile -InterfaceIndex {0} -NetworkCategory Private" -f $p.InterfaceIndex)
}
if (-not $publicProfiles) {
    Write-Host "network: active profile(s) are Private/Domain - firewall rule is effective"
}

# --- 3. At-logon server task (mirrors ops/windows-tasks.ps1 style) ---
$taskName = "HB API Server"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}
# Stop-ScheduledTask can orphan the python child; kill any listener still
# holding the LAN port so the fresh instance can bind.
Start-Sleep -Seconds 2
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$serve`"" -WorkingDirectory $backend
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "home-buying platform: LAN server (API + SPA)" -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "registered + started: $taskName (at logon -> ops/serve.ps1 -> hb serve on 0.0.0.0:$port)"
Write-Host "note: the task starts at logon, not boot; the server is up only while you are logged in"

Write-Host "`nshare this URL on your wifi: http://$($env:COMPUTERNAME.ToLower()).local:$port (or http://<this-LAN-IP>:$port) - any device, nothing to install."
