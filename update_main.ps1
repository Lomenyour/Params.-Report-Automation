param([string]$TestName='GTU_Report_Desktop_Test')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath($PSScriptRoot)
if ($TestName -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid test build name.' }
$source=Join-Path $taskRoot "dist_test\$TestName"
$target=Join-Path $taskRoot 'dist\GTU_Report'
$stamp=(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[guid]::NewGuid().ToString('N').Substring(0,8)
$stage=Join-Path $taskRoot "build_test\main_stage_$stamp\GTU_Report"
$archive=Join-Path $taskRoot "archive_builds\main_before_$stamp\GTU_Report"
foreach ($path in @($source,$target,$stage,$archive)) {
    if (-not [IO.Path]::GetFullPath($path).StartsWith($taskRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Promotion path escapes the project.'
    }
}
if (Get-Process -Name GTU_Report,$TestName -ErrorAction SilentlyContinue) { throw 'Close main and test applications before updating.' }
if (-not (Test-Path -LiteralPath (Join-Path $source "$TestName.exe"))) { throw 'Test EXE is missing.' }
& (Join-Path $taskRoot 'sync_report_templates.ps1') -TestName $TestName
py -B -X utf8 (Join-Path $taskRoot 'tools\verify_desktop_bundle.py') $source
if ($LASTEXITCODE -ne 0) { throw 'The test package does not match current sources.' }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
& robocopy $source $stage /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Package copy failed: $LASTEXITCODE" }
Move-Item -LiteralPath (Join-Path $stage "$TestName.exe") -Destination (Join-Path $stage 'GTU_Report.exe')
# Preserve the old main application's local data and completed reports.
foreach ($relative in @('data','word_auto\reports')) {
    $old=Join-Path $target $relative
    if (Test-Path -LiteralPath $old -PathType Container) {
        $new=Join-Path $stage $relative
        New-Item -ItemType Directory -Force -Path $new | Out-Null
        & robocopy $old $new /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Local data copy failed: $relative" }
    }
}
py -B -X utf8 (Join-Path $taskRoot 'tools\verify_desktop_bundle.py') $stage --exe-name GTU_Report
if ($LASTEXITCODE -ne 0) { throw 'Staged main package verification failed.' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $archive),(Split-Path -Parent $target) | Out-Null
$hadMain=Test-Path -LiteralPath $target -PathType Container
if ($hadMain) { Move-Item -LiteralPath $target -Destination $archive }
try { Move-Item -LiteralPath $stage -Destination $target }
catch {
    if ($hadMain -and -not (Test-Path -LiteralPath $target)) { Move-Item -LiteralPath $archive -Destination $target }
    throw
}
Write-Output "Main EXE: $target\GTU_Report.exe"
if ($hadMain) { Write-Output "Previous main preserved: $archive" }
