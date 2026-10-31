# Перезапуск OpenRGB с правами администратора и проверка SDK-сервера.
# Нужен, если SDK-сервер принимает TCP, но не отвечает на пакеты.
$root = Split-Path -Parent $PSScriptRoot
$exe = "C:\Program Files\OpenRGB\OpenRGB.exe"
$out = Join-Path $root ".cache\openrgb_after_restart.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $root ".cache") | Out-Null

Get-Process OpenRGB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath $exe -ArgumentList "--server","--startminimized"
Start-Sleep -Seconds 8

Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") "tools\openrgb_probe.py" *> $out
