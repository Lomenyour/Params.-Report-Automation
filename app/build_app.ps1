param([switch]$UseVerifiedTest)
$ErrorActionPreference = 'Stop'
$colleagueRoot = Split-Path -Parent $PSScriptRoot
if (-not $UseVerifiedTest) {
    & (Join-Path $colleagueRoot 'build_gui.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Rotor Test build failed.' }
}
py -B -X utf8 (Join-Path $colleagueRoot 'tools\build_colleague_package.py')
if ($LASTEXITCODE -ne 0) { throw 'Colleague package verification/build failed.' }
