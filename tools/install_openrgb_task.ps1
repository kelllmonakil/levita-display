# Registers OpenRGB to start at logon with the SDK server, elevated.
# Run as administrator:
#   powershell -ExecutionPolicy Bypass -File tools\install_openrgb_task.ps1
# Remove:
#   powershell -ExecutionPolicy Bypass -File tools\install_openrgb_task.ps1 -Uninstall
param([switch]$Uninstall)

$taskName = 'Levita OpenRGB SDK'
$exe = 'C:\Program Files\OpenRGB\OpenRGB.exe'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "task removed: $taskName"
    exit 0
}

if (-not (Test-Path $exe)) { throw "Missing $exe" }

$action = New-ScheduledTaskAction -Execute $exe -Argument '--server --startminimized' -WorkingDirectory (Split-Path $exe)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "task registered: $taskName"

Get-Process OpenRGB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $taskName
Write-Output "OpenRGB started with --server"
