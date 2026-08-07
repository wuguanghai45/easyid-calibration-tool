#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Register a Windows Scheduled Task to start the EasyID calibration web server at boot / logon.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "EasyID-Calibration-Web",
    [int]$StartupDelaySeconds = 30,
    [switch]$AsSystem,
    [switch]$NoStartNow
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
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pythonOnPath -and -not $pyLauncher) {
        Write-Warning "No .venv Python and no 'python'/'py' on PATH. start_web.bat will fail until Python is available."
    } else {
        Write-Warning "No .venv found at $VenvPython; start_web.bat will use PATH python/py."
    }
} else {
    Write-Host "Using venv Python: $VenvPython"
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

$delayIso = "PT{0}S" -f $StartupDelaySeconds

# Run via cmd /c so WorkingDirectory + bat relative paths resolve reliably.
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c call `"$StartBat`"" `
    -WorkingDirectory $RepoRoot

# At logon (factory PCs usually auto-login) + at startup with delay.
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonTrigger.Delay = $delayIso

$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = $delayIso

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
# Hide console window when the task runs (supported on Windows 8+ / Server 2012+).
if ($null -ne ($settings | Get-Member -Name Hidden -ErrorAction SilentlyContinue)) {
    $settings.Hidden = $true
}

if ($AsSystem) {
    # Optional: boot without interactive login (may miss user-only Python PATH).
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $triggers = @($startupTrigger)
    Write-Host "Principal: SYSTEM (AtStartup only)"
} else {
    # Default: current user — can see user-installed Python / .venv; works with auto-logon.
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Highest
    $triggers = @($logonTrigger, $startupTrigger)
    Write-Host "Principal: $env:USERNAME (AtLogOn + AtStartup)"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Start EasyID DataMatrix calibration web (run_web.py) at logon/startup." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "  Repo:     $RepoRoot"
Write-Host "  Launcher: $StartBat"
Write-Host "  Delay:    ${StartupDelaySeconds}s"
Write-Host "  Logs:     $(Join-Path $RepoRoot 'logs')"

if (-not $NoStartNow) {
    Write-Host "Starting task now for verification..."
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host ("  LastTaskResult={0} LastRunTime={1}" -f $info.LastTaskResult, $info.LastRunTime)
    Write-Host "  If LastTaskResult is 0/267009 and port 8080 listens, autostart works."
    Write-Host "  Check log: $(Join-Path $RepoRoot 'logs')"
}

Write-Host "Verify: Get-ScheduledTask -TaskName '$TaskName' | Format-List *"
Write-Host "Manual start: Start-ScheduledTask -TaskName '$TaskName'"
