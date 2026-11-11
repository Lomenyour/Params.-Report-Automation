# Open an exported workbook in an isolated Excel instance, read-only.
param([Parameter(Mandatory=$true)][string]$Book,
      [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$qaExcel = $null
$qaBook = $null
$destination = [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
New-Item -ItemType Directory -Force -Path $destination | Out-Null
try {
    $qaExcel = New-Object -ComObject Excel.Application
    $qaExcel.Visible = $false
    $qaExcel.DisplayAlerts = $false
    $qaExcel.EnableEvents = $false
    $qaExcel.AutomationSecurity = 3
    $qaBook = $qaExcel.Workbooks.Open((Resolve-Path -LiteralPath $Book).Path, 0, $true)
    $sheet = $qaBook.Worksheets.Item('Графики')
    $chartObject = $null
    $series = @()
    $names = @()
    foreach ($object in $sheet.ChartObjects()) {
        $candidate = $object.Chart
        for ($index = 1; $index -le $candidate.SeriesCollection().Count; $index++) {
            $item = $candidate.SeriesCollection($index)
            $names += $item.Name
            if ($item.Name -eq 'Перепад давления на ФСО') {
                $chartObject = $object
                $series += $item
            }
        }
    }
    if ($series.Count -ne 1) { throw ('Expected one independent FSO series: ' + ($names -join '; ')) }
    $chart = $chartObject.Chart
    $fso = $series[0]
    if ($fso.AxisGroup -ne 1) { throw 'FSO is not on the pressure axis.' }
    if ($fso.MarkerForegroundColor -ne 0xCFBE17) { throw 'FSO marker color does not match #17BECF.' }
    $values = @($fso.Values)
    if ($values.Count -lt 2) { throw 'FSO has no chart points.' }
    if ($chart.Axes(2).MinimumScale -ne 0) { throw 'Pressure axis minimum changed.' }
    $found = $sheet.Range('A40:W1000').Find('ФСО, Па')
    if ($null -eq $found) { throw 'FSO boundary values are missing.' }
    $image = Join-Path $destination 'pressure_excel.png'
    $chartObject.Activate() | Out-Null
    $chart.Refresh()
    if (-not $chart.Export($image, 'PNG')) { throw 'Excel did not export pressure chart.' }
    $report = [pscustomobject]@{
        Name = $fso.Name; Formula = $fso.Formula; Count = $values.Count;
        First = $values[0]; Last = $values[-1]; AxisGroup = $fso.AxisGroup;
        Color = $fso.MarkerForegroundColor; BoundaryCell = $found.Address(); Image = $image
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'verification.json') -Encoding UTF8
    $report | ConvertTo-Json -Depth 5
} finally {
    if ($null -ne $qaBook) { $qaBook.Close($false) }
    if ($null -ne $qaExcel) {
        $qaExcel.Quit()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($qaExcel) | Out-Null
    }
}
