param([string]$Name = "GTU_Report_Test")

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (Get-Process -Name $Name -ErrorAction SilentlyContinue) {
    throw "Close $Name.exe before rebuilding the test version."
}

$templateSource = Join-Path $PSScriptRoot "word_auto\templates"
$testRoot = Join-Path $PSScriptRoot "dist_test\$Name"

# Qt использует системную ICU Windows. Каталог Poppler в PATH окружения
# инструментов может подставить другую icuuc.dll с несовместимыми экспортами.
# Меняется только PATH процесса сборки; пользовательское окружение не меняется.
$buildOriginalPath = $env:PATH
$buildSystemDir = [Environment]::GetFolderPath('System')
$env:PATH = (($buildOriginalPath -split ';' | Where-Object {
    $_ -and ([string]::Equals($_.TrimEnd('\'), $buildSystemDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) -or
             -not (Test-Path -LiteralPath (Join-Path $_ 'icuuc.dll')))
}) -join ';')

py -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --icon "$PSScriptRoot\scr\desktop_ui\app-icon.ico" `
    --name $Name `
    --paths "$PSScriptRoot\scr" `
    --collect-all CoolProp `
    --collect-all matplotlib `
    --collect-all python_calamine `
    --collect-all openpyxl `
    --add-data "$PSScriptRoot\config;config" `
    --add-data "$PSScriptRoot\scr\desktop_ui;desktop_ui" `
    --add-data "$templateSource;word_auto\templates" `
    --distpath "$PSScriptRoot\dist_test" `
    --workpath "$PSScriptRoot\build_test\work" `
    --specpath "$PSScriptRoot\build_test" `
    "$PSScriptRoot\scr\desktop_app.py"

$env:PATH = $buildOriginalPath

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller exited with code $LASTEXITCODE. Build failed."
}

# Рабочие шаблоны тестовой сборки можно менять без пересборки EXE.
$templateTarget = Join-Path $testRoot "word_auto\templates"
New-Item -ItemType Directory -Force -Path $templateTarget | Out-Null
Copy-Item -Path (Join-Path $templateSource "*") -Destination $templateTarget -Recurse -Force

# Справочники можно обновлять рядом с EXE без изменения расчётных модулей.
$configTarget = Join-Path $testRoot "config"
New-Item -ItemType Directory -Force -Path $configTarget | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "config\stations.json") -Destination $configTarget -Force

Write-Host "Test EXE: $testRoot\$Name.exe"
