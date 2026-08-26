# Build and flash Marlin firmware via PlatformIO.
# Usage (turn VPN OFF for the first run - downloads are much faster):
#   powershell scripts\flash.ps1            # auto-detect COM port
#   powershell scripts\flash.ps1 COM11      # explicit COM port
$ErrorActionPreference = "Stop"
$root   = Split-Path $PSScriptRoot -Parent
$py     = Join-Path $root ".venv\Scripts\python.exe"
$marlin = Join-Path $root "firmware\Marlin"

if (-not (Test-Path $marlin)) {
    throw "firmware\Marlin not found. Run first: .venv\Scripts\python scripts\setup_firmware.py"
}

Write-Host "[1/3] PlatformIO (first run downloads ~100 MB)..." -ForegroundColor Cyan
& $py -m pip install -q platformio
if ($LASTEXITCODE -ne 0) { throw "pip install platformio failed" }

Write-Host "[2/3] Build (first build takes several minutes - this is normal)..." -ForegroundColor Cyan
Push-Location $marlin
try {
    & $py -m platformio run -e mega2560
    if ($LASTEXITCODE -ne 0) { throw "Build failed - send the FULL output to the assistant" }

    Write-Host "[3/3] Upload to board..." -ForegroundColor Cyan
    if ($Port) {
        & $py -m platformio run -e mega2560 -t upload --upload-port $Port
    } else {
        & $py -m platformio run -e mega2560 -t upload
    }
    if ($LASTEXITCODE -ne 0) { throw "Upload failed - check USB cable and COM port" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "DONE! Now check the board:" -ForegroundColor Green
Write-Host "  .venv\Scripts\python scripts\smoke_serial.py --port COM11   (use your port)"
