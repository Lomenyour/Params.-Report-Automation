$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (Get-Process -Name "GTU_Report_Test" -ErrorAction SilentlyContinue) {
    throw "Close GTU_Report_Test.exe before rebuilding the test version."
}

$templateSource = Join-Path $PSScriptRoot "word_auto\templates"
$testRoot = Join-Path $PSScriptRoot "dist_test\GTU_Report_Test"

py -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name GTU_Report_Test `
    --paths "$PSScriptRoot\scr" `
    --collect-all CoolProp `
    --collect-all matplotlib `
    --collect-all python_calamine `
    --collect-all openpyxl `
    --add-data "$templateSource;word_auto\templates" `
    --distpath "$PSScriptRoot\dist_test" `
    --workpath "$PSScriptRoot\build_test\work" `
    --specpath "$PSScriptRoot\build_test" `
    "$PSScriptRoot\scr\app.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller exited with code $LASTEXITCODE. Build failed."
}

# Рабочие шаблоны тестовой сборки можно менять без пересборки EXE.
$templateTarget = Join-Path $testRoot "word_auto\templates"
New-Item -ItemType Directory -Force -Path $templateTarget | Out-Null
Copy-Item -Path (Join-Path $templateSource "*") -Destination $templateTarget -Recurse -Force

Write-Host "Test EXE: $testRoot\GTU_Report_Test.exe"
