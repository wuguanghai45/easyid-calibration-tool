#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Register a Windows Scheduled Task to start the EasyID calibration web server at boot.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "EasyID-Calibration-Web",
    [int]$StartupDelaySeconds = 30
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$StartBat = Join-Path $ScriptDir "start_web.bat"

if (-not (Test-Path -LiteralPath $StartBat)) {
    throw "Launcher not found: $StartBat"
}

# Warnings only — do not fail install if optional assets are missing.
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$MvsdkDll = Join-Path $RepoRoot "Runtime\x64\MVSDKmd.dll"
$FrontendDist = Join-Path $RepoRoot "frontend\dist\index.html"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $pythonOnPath = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonOnPath) {
        Write-Warning "No .venv Python and no 'python' on PATH. start_web.bat will fail until Python is available."
    } else {
        Write-Warning "No .venv found at $VenvPython; start_web.bat will use PATH python ($($pythonOnPath.Source))."
    }
}

if (-not (Test-Path -LiteralPath $MvsdkDll)) {
    Write-Warning "MVSDK DLL missing: $MvsdkDll (camera features will not work until Runtime/x64 is installed)."
}

if (-not (Test-Path -LiteralPath $FrontendDist)) {
    Write-Warning "frontend/dist not built. Run: cd frontend && npm install && npm run build"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

$delay = [TimeSpan]::FromSeconds($StartupDelaySeconds)
$delayIso = "PT{0}S" -f [int]$delay.TotalSeconds

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$StartBat`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = $delayIso

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# SYSTEM: run at boot without requiring an interactive login.
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Start EasyID DataMatrix calibration web (run_web.py) at system startup." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "  Repo:    $RepoRoot"
Write-Host "  Launcher:$StartBat"
Write-Host "  Delay:   ${StartupDelaySeconds}s after startup"
Write-Host "  Logs:    $(Join-Path $RepoRoot 'logs')"
Write-Host "Verify in taskschd.msc, or: Get-ScheduledTask -TaskName '$TaskName'"
