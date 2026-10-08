$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$exe = Join-Path $PSScriptRoot "dist\GTU_Report.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build the EXE first: powershell -ExecutionPolicy Bypass -File .\build_app.ps1"
}

$delivery = Join-Path $PSScriptRoot "delivery\GTU_Report"
$archive = Join-Path $PSScriptRoot "delivery\GTU_Report_for_colleague.zip"

if (Test-Path -LiteralPath $delivery) {
    Remove-Item -LiteralPath $delivery -Recurse -Force
}
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}

New-Item -ItemType Directory -Path $delivery -Force | Out-Null
Copy-Item -LiteralPath $exe -Destination $delivery
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.txt") -Destination $delivery
Compress-Archive -Path (Join-Path $delivery "*") -DestinationPath $archive -Force

Write-Host "Delivery archive: $archive"
