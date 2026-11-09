# Native Excel object-model check of generated RH diagrams; input stays read-only.
param([Parameter(Mandatory=$true)][string]$Book,
      [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$qaExcel = $null
$qaBook = $null
$reports = @()
$destination = [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
New-Item -ItemType Directory -Force -Path $destination | Out-Null
try {
    $qaExcel = New-Object -ComObject Excel.Application
    $qaExcel.Visible = $false
    $qaExcel.DisplayAlerts = $false
    $qaBook = $qaExcel.Workbooks.Open((Resolve-Path -LiteralPath $Book).Path, 0, $true)
    $number = 0
    foreach ($item in $qaBook.Worksheets.Item('Графики').ChartObjects()) {
        $chart = $item.Chart
        if ($chart.SeriesCollection(1).Name -ne 'Условно-чистая') { continue }
        $number++
        $image = Join-Path $destination ('rh_' + $number + '.png')
        if (-not $chart.Export($image, 'PNG')) { throw 'Excel did not export RH chart.' }
        $xmin = $chart.Axes(1).MinimumScale
        $xspan = $chart.Axes(1).MaximumScale - $xmin
        $ymin = $chart.Axes(2).MinimumScale
        $yspan = $chart.Axes(2).MaximumScale - $ymin
        $plot = $chart.PlotArea
        $vectors = @()
        $errors = @()
        $geometry = @()
        foreach ($indices in @(@(5,6),@(7,8))) {
            $arrow = $chart.SeriesCollection($indices[0])
            $label = $chart.SeriesCollection($indices[1]).Points(1).DataLabel
            $xs = @($arrow.XValues)
            $ys = @($arrow.Values)
            $tailX = $plot.InsideLeft + ($xs[0]-$xmin)/$xspan*$plot.InsideWidth
            $tailY = $plot.InsideTop + (1-($ys[0]-$ymin)/$yspan)*$plot.InsideHeight
            $edgeY = if ($indices[0] -eq 5) { $label.Top + $label.Height } else { $label.Top }
            $errors += [Math]::Abs($tailX-($label.Left+$label.Width/2))
            $errors += [Math]::Abs($tailY-$edgeY)
            $vectorX = ($xs[1]-$xs[0])/$xspan*$plot.InsideWidth
            $vectorY = -($ys[1]-$ys[0])/$yspan*$plot.InsideHeight
            $vectors += ,@($vectorX,$vectorY)
            $geometry += [pscustomobject]@{Series=$indices[0];Name=$arrow.Name;X=$xs;Y=$ys;
                TailX=$tailX;TailY=$tailY;FrameX=($label.Left+$label.Width/2);FrameY=$edgeY}
        }
        $cross = $vectors[0][0]*$vectors[1][1]-$vectors[0][1]*$vectors[1][0]
        $scale = [Math]::Sqrt(($vectors[0][0]*$vectors[0][0]+$vectors[0][1]*$vectors[0][1]) *
                            ($vectors[1][0]*$vectors[1][0]+$vectors[1][1]*$vectors[1][1]))
        $reports += [pscustomobject]@{Chart=$number; Legend=$chart.Legend.LegendEntries().Count;
            MaxFrameEdgeErrorPoints=($errors|Measure-Object -Maximum).Maximum;
            ParallelSine=([Math]::Abs($cross)/$scale); Image=$image; Arrows=$geometry}
        if ($reports[-1].MaxFrameEdgeErrorPoints -gt .01 -or $reports[-1].ParallelSine -gt 1e-8) {
            throw 'Native RH arrows do not match frame centers or are not parallel.'
        }
    }
    if (-not $number) { throw 'No RH charts found.' }
    $reports | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $destination 'verification.json') -Encoding UTF8
    $reports | Select-Object Chart,Legend,MaxFrameEdgeErrorPoints,ParallelSine,Image | ConvertTo-Json
} finally {
    if ($null -ne $qaBook) { $qaBook.Close($false) }
    if ($null -ne $qaExcel) {
        $qaExcel.Quit()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($qaExcel) | Out-Null
    }
}
