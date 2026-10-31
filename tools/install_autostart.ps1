# Autostart for Levita Display.
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -WithOpenRGB
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Uninstall
param(
    [switch]$Uninstall,
    [switch]$WithOpenRGB
)

$root = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'Levita Display.lnk'
$openrgbLnk = Join-Path $startup 'OpenRGB (SDK server).lnk'

if ($Uninstall) {
    Remove-Item $lnk -ErrorAction SilentlyContinue
    Remove-Item $openrgbLnk -ErrorAction SilentlyContinue
    Write-Output "Autostart removed."
    exit 0
}

$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "Missing $pythonw - create the .venv first (see README)."
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($lnk)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"main.py" --backend trcc'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = (Join-Path $root 'assets\icon.ico')
$shortcut.WindowStyle = 7
$shortcut.Description = 'Levita Display - GIF and monitoring on the pump'
$shortcut.Save()
Write-Output "Autostart: $lnk"

if ($WithOpenRGB) {
    $openrgb = 'C:\Program Files\OpenRGB\OpenRGB.exe'
    if (-not (Test-Path $openrgb)) {
        throw "Missing $openrgb"
    }
    $s = $wsh.CreateShortcut($openrgbLnk)
    $s.TargetPath = $openrgb
    $s.Arguments = '--server --startminimized'
    $s.WorkingDirectory = Split-Path $openrgb
    $s.WindowStyle = 7
    $s.Description = 'OpenRGB with SDK server for Levita Display'
    $s.Save()
    Write-Output "OpenRGB autostart: $openrgbLnk"
    Write-Output "Note: OpenRGB needs administrator rights for SMBus. If lighting does not work,"
    Write-Output "add OpenRGB to Task Scheduler with 'Run with highest privileges'."
}

Write-Output "Done. Verify by signing out and back in."
