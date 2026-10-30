# Registers the HB scheduled tasks (docs/05-pipelines.md §2).
# Idempotent: -Force updates tasks in place; safe to re-run any time.
# Tasks run as the current interactive user.
#
# The pipeline tasks fire EVERY HOUR (and 10 min after logon) with --catch-up:
# `hb` runs the job only when its latest schedule slot (SCAN_TIMES /
# DAILY_TIMES, default 05:00+15:00 / 04:00 local) has no completed run yet,
# and otherwise exits at once. A slot missed to sleep, a crash or a failed run
# is therefore retried within the hour instead of silently skipped.
#
# `uv run --no-sync`: a task never re-syncs the venv. A sync rewrites
# .venv\Scripts\hb.exe, which the always-on API server holds open, so a synced
# run dies before `hb` starts whenever pyproject.toml/uv.lock changed. The venv
# is synced by `make install` / `make deploy-windows` while the server is stopped.
#
# `conhost --headless`: uv is a console program, so launched directly every
# hourly run would flash a terminal window on the desktop. The headless host
# gives it a console with no window; the task still runs in the user's session,
# so toast alerts keep working.

$ErrorActionPreference = "Stop"

$backend = (Resolve-Path (Join-Path $PSScriptRoot "..\backend")).Path
$uv = (Get-Command uv).Source
$conhost = Join-Path $env:SystemRoot "System32\conhost.exe"

function Register-HbTask {
    param([string]$Name, [string]$At, [string]$HbArgs)

    $action = New-ScheduledTaskAction -Execute $conhost `
        -Argument "--headless `"$uv`" run --no-sync hb $HbArgs" -WorkingDirectory $backend
    $hourly = New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours 1)
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Delay = "PT10M"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($hourly, $logon) `
        -Settings $settings -Description "home-buying platform: hb $HbArgs" -Force | Out-Null
    Write-Host "registered: $Name (hourly from $At + at logon -> hb $HbArgs)"
}

Register-HbTask -Name "HB Daily Pipelines" -At "00:00" -HbArgs "pipeline daily --catch-up"
Register-HbTask -Name "HB Listing Scan"    -At "00:00" -HbArgs "pipeline listing-scan --catch-up"
# delivers only undelivered alerts, so hourly is harmless and picks up each scan's
Register-HbTask -Name "HB Alerts Send"     -At "00:30" -HbArgs "alerts send"

Write-Host "`nAll tasks registered. Inspect with: Get-ScheduledTask -TaskName 'HB *'"
