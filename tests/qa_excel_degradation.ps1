# Read-only native Excel object-model verification of a generated QA workbook.
param([Parameter(Mandatory=$true)][string]$Book,
      [Parameter(Mandatory=$true)][string]$OutputImage)
$ErrorActionPreference = 'Stop'
$qaExcel = $null
$qaBook = $null
try {
    $qaExcel = New-Object -ComObject Excel.Application
    $qaExcel.Visible = $false
    $qaExcel.DisplayAlerts = $false
    $qaBook = $qaExcel.Workbooks.Open((Resolve-Path -LiteralPath $Book).Path, 0, $true)
    $qaChart = $null
    foreach ($qaObject in $qaBook.Worksheets.Item('Графики').ChartObjects()) {
        $candidate = $qaObject.Chart
        if ($candidate.SeriesCollection().Count -and
            $candidate.SeriesCollection(1).Name -eq 'Nприв, МВт') {
            $qaChart = $candidate
            break
        }
    }
    if ($null -eq $qaChart) { throw 'General degradation chart was not found.' }
    $trends = 0
    foreach ($series in $qaChart.SeriesCollection()) { $trends += $series.Trendlines().Count }
    if ($qaChart.Legend.LegendEntries().Count -ne 4) { throw 'Expected four metric legend entries.' }
    $imagePath = [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputImage))
    if (-not $qaChart.Export($imagePath, 'PNG')) { throw 'Excel did not export the chart.' }
    [pscustomobject]@{
        ExcelVersion = $qaExcel.Version
        Series = $qaChart.SeriesCollection().Count
        LinearTrends = $trends
        LegendEntries = $qaChart.Legend.LegendEntries().Count
        MainMin = $qaChart.Axes(2,1).MinimumScale
        MainMax = $qaChart.Axes(2,1).MaximumScale
        VnaMin = $qaChart.Axes(2,2).MinimumScale
        VnaMax = $qaChart.Axes(2,2).MaximumScale
        DateText = $qaBook.Worksheets.Item('Данные деградации ГТУ').Range('A6').Text
        Image = $imagePath
    } | ConvertTo-Json
} finally {
    if ($null -ne $qaBook) { $qaBook.Close($false) }
    if ($null -ne $qaExcel) {
        $qaExcel.Quit()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($qaExcel) | Out-Null
    }
}
