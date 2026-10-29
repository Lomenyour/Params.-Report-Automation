param(
    [string]$TestName = 'GTU_Report_Desktop_Test',
    [ValidateSet('Auto','Source','Test')][string]$Prefer = 'Auto'
)
$ErrorActionPreference = 'Stop'
if ($TestName -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid test build name.' }
$taskRoot = $PSScriptRoot
$sourceDir = Join-Path $taskRoot 'word_auto\templates'
$testDir = Join-Path $taskRoot "dist_test\$TestName\word_auto\templates"
$stateDir = Join-Path $taskRoot 'build_test\template_sync'
$statePath = Join-Path $stateDir "$TestName.json"
New-Item -ItemType Directory -Force -Path $sourceDir,$testDir,$stateDir | Out-Null
$state = @{}
if (Test-Path -LiteralPath $statePath) {
    $json = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $json.PSObject.Properties) { $state[$property.Name] = [string]$property.Value }
}
function TemplateHash([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
$names = @(Get-ChildItem -LiteralPath $sourceDir,$testDir -Filter '*.docx' -File |
    Where-Object { -not $_.Name.StartsWith('~$') } | Select-Object -ExpandProperty Name -Unique)
$plan = @()
foreach ($name in $names) {
    $source = Join-Path $sourceDir $name
    $test = Join-Path $testDir $name
    $sourceHash,$testHash = (TemplateHash $source),(TemplateHash $test)
    if ($sourceHash -eq $testHash) { continue }
    $direction = $Prefer
    if ($direction -eq 'Auto') {
        if (-not $sourceHash) { $direction = 'Test' }
        elseif (-not $testHash) { $direction = 'Source' }
        elseif ($state.ContainsKey($name) -and $sourceHash -eq $state[$name]) { $direction = 'Test' }
        elseif ($state.ContainsKey($name) -and $testHash -eq $state[$name]) { $direction = 'Source' }
        else { throw "Template conflict: $name. Both versions are preserved. Use -Prefer Source or -Prefer Test explicitly." }
    }
    $from,$to = if ($direction -eq 'Test') { $test,$source } else { $source,$test }
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { throw "Preferred template is missing: $from" }
    $plan += [pscustomobject]@{From=$from;To=$to;Name=$name;Direction=$direction}
}
# Validate every conflict before copying any file.
$backupDir = Join-Path $taskRoot ('archive_builds\template_sync_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8))
foreach ($change in $plan) {
    if (Test-Path -LiteralPath $change.To) {
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Copy-Item -LiteralPath $change.To -Destination (Join-Path $backupDir ($change.Direction+'_'+$change.Name))
    }
    Copy-Item -LiteralPath $change.From -Destination $change.To -Force
    Write-Output ("Template synchronized from {0}: {1}" -f $change.Direction,$change.Name)
}
$updated = @{}
foreach ($name in $names) {
    $sourceHash = TemplateHash (Join-Path $sourceDir $name)
    if ($sourceHash -ne (TemplateHash (Join-Path $testDir $name))) { throw "Template verification failed: $name" }
    $updated[$name] = $sourceHash
    $fallbackDir = Join-Path $taskRoot "dist_test\$TestName\_internal\word_auto\templates"
    if (Test-Path -LiteralPath $fallbackDir -PathType Container) {
        Copy-Item -LiteralPath (Join-Path $sourceDir $name) -Destination (Join-Path $fallbackDir $name) -Force
    }
}
$tempState = $statePath + '.tmp'
$updated | ConvertTo-Json | Set-Content -LiteralPath $tempState -Encoding UTF8
Move-Item -LiteralPath $tempState -Destination $statePath -Force
Write-Output ('Templates verified: '+$names.Count)
