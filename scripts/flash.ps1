# Сборка и заливка прошивки Marlin через PlatformIO.
# Использование (VPN лучше выключить — будет быстрее):
#   powershell scripts\flash.ps1          # автоопределение COM-порта
#   powershell scripts\flash.ps1 COM5     # явный порт
$ErrorActionPreference = "Stop"
$root  = Split-Path $PSScriptRoot -Parent
$py    = Join-Path $root ".venv\Scripts\python.exe"
$marlin = Join-Path $root "firmware\Marlin"

if (-not (Test-Path $marlin)) {
    throw "Нет папки firmware\Marlin — сначала запустите: .venv\Scripts\python scripts\setup_firmware.py"
}

Write-Host "[1/3] PlatformIO (при первом запуске скачается ~100 МБ)..." -ForegroundColor Cyan
& $py -m pip install -q platformio
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить platformio" }

Write-Host "[2/3] Сборка (первая — несколько минут, это нормально)..." -ForegroundColor Cyan
Push-Location $marlin
try {
    & $py -m platformio run -e mega2560
    if ($LASTEXITCODE -ne 0) { throw "Ошибка сборки — пришлите вывод целиком ассистенту" }

    Write-Host "[3/3] Заливка..." -ForegroundColor Cyan
    if ($Port) {
        & $py -m platformio run -e mega2560 -t upload --upload-port $Port
    } else {
        & $py -m platformio run -e mega2560 -t upload
    }
    if ($LASTEXITCODE -ne 0) { throw "Ошибка заливки — проверьте USB-кабель и COM-порт" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "ГОТОВО! Проверка платы:" -ForegroundColor Green
Write-Host "  .venv\Scripts\python scripts\smoke_serial.py --port COM5"
Write-Host "(замените COM5 на ваш порт; скорость уже 250000)"
