# Recreate the complete package from the verified current Rotor Test.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build_app.ps1') -UseVerifiedTest
if ($LASTEXITCODE -ne 0) { throw 'Colleague delivery failed.' }
