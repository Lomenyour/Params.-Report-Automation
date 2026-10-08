$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

py -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name GTU_Report `
    --paths "$PSScriptRoot\scr" `
    --collect-all CoolProp `
    --collect-all matplotlib `
    "$PSScriptRoot\scr\app.py"

Write-Host "Готово. EXE находится в: $PSScriptRoot\dist\GTU_Report\GTU_Report.exe"
