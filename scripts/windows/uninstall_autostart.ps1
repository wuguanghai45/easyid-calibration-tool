#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Remove the EasyID calibration web autostart Scheduled Task.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "EasyID-Calibration-Web"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Scheduled task not found: $TaskName (nothing to remove)."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
