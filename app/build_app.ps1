$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

py -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name GTU_Report `
    --paths "$PSScriptRoot\src" `
    --collect-all CoolProp `
    --collect-all matplotlib `
    --collect-all python_calamine `
    "$PSScriptRoot\src\app.py"

Write-Host "Build complete: $PSScriptRoot\dist\GTU_Report.exe"
