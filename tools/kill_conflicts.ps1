# Stops and disables MSI/Mystic Light services and kills RGB-control apps.
# Run as administrator:
#   powershell -ExecutionPolicy Bypass -File tools\kill_conflicts.ps1
# Restore previous service startup types:
#   powershell -ExecutionPolicy Bypass -File tools\kill_conflicts.ps1 -Restore
param(
    [switch]$Restore
)

$root = Split-Path -Parent $PSScriptRoot
$backupPath = Join-Path $root '.cache\msi_services_backup.json'
$services = @(
    'Mystic_Light_Service',
    'LightKeeperService',
    'MSI_Center_Service',
    'MSI_Case_Service',
    'MSI_Companion_Service'
)
$processes = @(
    'MSI.CentralServer',
    'MSI.TerminalServer',
    'MSI Center',
    'Mystic Light',
    'LightKeeper',
    'SignalRGB',
    'iCUE'
)

if ($Restore) {
    if (-not (Test-Path $backupPath)) {
        Write-Output "No backup at $backupPath"
        exit 1
    }
    $backup = Get-Content $backupPath -Raw | ConvertFrom-Json
    foreach ($entry in $backup) {
        if (Get-Service -Name $entry.Name -ErrorAction SilentlyContinue) {
            Set-Service -Name $entry.Name -StartupType $entry.StartType
            if ($entry.Status -eq 'Running') { Start-Service -Name $entry.Name }
            Write-Output "restored $($entry.Name) -> $($entry.StartType)"
        }
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path (Split-Path $backupPath) | Out-Null
$saved = @()
foreach ($name in $services) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $svc) { continue }
    $saved += [pscustomobject]@{
        Name = $svc.Name
        StartType = $svc.StartType.ToString()
        Status = $svc.Status.ToString()
    }
}
$saved | ConvertTo-Json | Set-Content -Path $backupPath -Encoding UTF8
Write-Output "backup: $backupPath"

foreach ($name in $services) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $svc) { continue }
    try {
        Stop-Service -Name $name -Force -ErrorAction Stop
        Set-Service -Name $name -StartupType Disabled -ErrorAction Stop
        Write-Output "stopped+disabled: $name"
    } catch {
        Write-Output "failed: $name ($($_.Exception.Message))"
    }
}

foreach ($pname in $processes) {
    Get-Process -Name $pname -ErrorAction SilentlyContinue |
        ForEach-Object {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            Write-Output "killed: $pname ($($_.Id))"
        }
}

Write-Output "done. OpenRGB can now own the ARGB channel."
