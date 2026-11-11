# Native Excel reference for arithmetic errors inside larger expressions.
param([Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$excel=$null; $book=$null
try {
    $excel=New-Object -ComObject Excel.Application
    $excel.Visible=$false; $excel.DisplayAlerts=$false; $excel.EnableEvents=$false
    $book=$excel.Workbooks.Add()
    $cases=@(
        @{Formula='=1/(2/0)';Error=$true},
        @{Formula='=(2/0)^0';Error=$true},
        @{Formula='=IFERROR(1/(2/0),7)';Error=$false;Value=7.0},
        @{Formula='=1/EXP(1000)';Error=$true},
        @{Formula='=1/LN(0)';Error=$true},
        @{Formula='=100/(100/0)';Error=$true},
        @{Formula='=100/(100/20000)';Error=$false;Value=20000.0}
    )
    $reports=@()
    foreach ($case in $cases) {
        $cell=$book.Worksheets.Item(1).Cells.Item($reports.Count+1,1)
        $cell.Formula=$case.Formula
        $cell.Calculate()
        $errorValue=$cell.Text.StartsWith('#')
        if ($errorValue -ne $case.Error) { throw ('Unexpected error state: '+$case.Formula+' '+$cell.Text) }
        if (-not $errorValue -and [Math]::Abs($cell.Value2-$case.Value) -gt 1e-10) {
            throw ('Unexpected numeric value: '+$case.Formula)
        }
        $reports += [pscustomobject]@{Formula=$case.Formula;Error=$errorValue;
            Text=$cell.Text;ExpectedValue=$(if ($case.Error) { $null } else { $case.Value })}
    }
    $reports|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $Output -Encoding UTF8
    Write-Output ('PASS: '+$reports.Count+' native Excel arithmetic cases')
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) {
        $excel.Quit();[Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)|Out-Null
    }
}
