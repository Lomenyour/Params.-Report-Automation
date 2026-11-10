param([Parameter(Mandatory=$true)][ValidateSet('create','verify')][string]$Mode,
      [Parameter(Mandatory=$true)][string]$Folder)
$ErrorActionPreference='Stop'
$excel=$null; $book=$null
try {
    $excel=New-Object -ComObject Excel.Application
    $excel.Visible=$false; $excel.DisplayAlerts=$false; $excel.EnableEvents=$false
    if ($Mode -eq 'create') {
        $book=$excel.Workbooks.Add()
        $sheet=$book.Worksheets.Item(1);$sheet.Name='Данные'
        while ($book.Worksheets.Count -gt 1) { $book.Worksheets.Item($book.Worksheets.Count).Delete() }
        $coeff=$book.Worksheets.Add([Type]::Missing,$sheet);$coeff.Name='Коэффициенты'
        $coeff.Range('B2').Value2=10
        $coeff.Range('A1').Value2='Не изменять вспомогательный лист'
        $headers=@('Часы','Дата','N, МВт','Результат','Среднее','Константа','Без выгрузки','Абсолютные ссылки','Проверка ошибки','Текст')
        for ($i=0;$i -lt $headers.Count;$i++) { $sheet.Cells.Item(1,$i+1).Value2=$headers[$i] }
        $hours=@(0,0.5,1.5,2,2.5,3)
        for ($i=0;$i -lt $hours.Count;$i++) {
            $r=$i+2
            $sheet.Cells.Item($r,1).Value2=[double]$hours[$i]
            $dateSerial=([datetime]'2026-01-01').AddHours($hours[$i]).AddMilliseconds(4).ToOADate()
            $sheet.Cells.Item($r,2).Value2=[double]$dateSerial
            $sheet.Cells.Item($r,3).Value2=[double](10+$i)
            $sheet.Cells.Item($r,4).Formula="=C$r*2+`$F`$2+'Коэффициенты'!`$B`$2"
            if ($r%2 -eq 1) { $sheet.Cells.Item($r,5).Formula="=AVERAGE(C$($r-1):C$r)" }
            $sheet.Cells.Item($r,6).Value2=3.0
            $sheet.Cells.Item($r,7).Value2=123.0
            $sheet.Cells.Item($r,8).FormulaArray="=`$C$r+C`$2+'Коэффициенты'!`$B`$2"
            $sheet.Cells.Item($r,9).Formula="=100/C$r"
        }
        $sheet.Range('A10').Value2='Итого'
        $sheet.Range('D10').Formula='=SUM(D2:D7)'
        $sheet.Range('A1:J1').Font.Bold=$true
        $sheet.Range('A2:J7').Interior.Color=15790320
        $sheet.Range('B:B').NumberFormatLocal='дд.мм.гггг чч:мм'
        $sheet.Range('B:B').ColumnWidth=22
        $sheet.Range('C:J').ColumnWidth=16
        $sheet.Range('A2:J7').RowHeight=19
        $null=$sheet.Range('C2').AddComment('Сохранить комментарий')
        $excel.CalculateFull()
        $book.SaveAs((Join-Path $Folder 'original.xlsx'),51)
        $book.SaveAs((Join-Path $Folder 'original.xlsm'),52)
        $book.Close($false);$book=$null
    } else {
        $report=@()
        foreach ($extension in @('xlsx','xlsm')) {
            $book=$excel.Workbooks.Open((Join-Path $Folder "updated.$extension"),0,$true)
            $sheet=$book.Worksheets.Item(1)
            if ($book.Worksheets.Count -ne 2 -or $book.Worksheets.Item(2).Name -cne 'Коэффициенты') { throw 'Lost original sheets' }
            if ($book.Worksheets.Item(2).Range('B2').Value2 -ne 10) { throw 'Changed coefficient' }
            $dates=@{};for($r=2;$r -le 20;$r++) {
                $value=$sheet.Cells.Item($r,2).Value2
                if ($value -is [double]) { $dates[[datetime]::FromOADate($value).ToString('yyyy-MM-dd HH:mm')]=$r }
            }
            if ($dates.Count -ne 10) { throw "Wrong date count $($dates.Count)" }
            foreach ($key in @('2025-12-31 23:30','2026-01-01 01:00','2026-01-01 03:30','2026-01-01 04:00')) {
                $r=$dates[$key]
                if (-not $sheet.Cells.Item($r,4).HasFormula) { throw "Missing formula $r" }
                if (-not $sheet.Cells.Item($r,8).HasArray -or $sheet.Cells.Item($r,8).CurrentArray.CountLarge -ne 1) { throw 'Single-cell array formula was not preserved' }
                if ($sheet.Cells.Item($r,7).Value2) { throw 'Unprovided measurement was repeated' }
                if ($sheet.Cells.Item($r,6).Value2 -ne 3) { throw 'Lost computed constant' }
                if ($sheet.Cells.Item($r,4).Interior.Color -ne 15790320 -or $sheet.Rows.Item($r).RowHeight -ne 19) { throw 'Lost formatting' }
            }
            $r=$dates['2026-01-01 00:00']
            if ($sheet.Cells.Item($r,3).Value2 -ne 20 -or $sheet.Cells.Item($r,4).Value2 -ne 53) { throw 'Overlap did not recalculate' }
            if ([datetime]::FromOADate($sheet.Cells.Item($r,2).Value2).Millisecond -ne 4) { throw 'Original timestamp changed' }
            if ($sheet.Cells.Item($r,7).Value2 -ne 123 -or -not $sheet.Cells.Item($r,3).Comment) { throw 'Changed unprovided field/comment' }
            $r=$dates['2026-01-01 01:00']
            if ($sheet.Cells.Item($r,4).Value2 -ne 57) { throw 'Inserted formula shifted incorrectly' }
            $r=$dates['2026-01-01 04:00']
            if ($sheet.Cells.Item($r,10).HasFormula -or $sheet.Cells.Item($r,10).Value2 -cne '=1+1') { throw 'Raw text was executed as formula' }
            $footer=$sheet.Cells.Find('Итого')
            if ($footer.Row -ne 14 -or -not $sheet.Cells.Item(14,4).HasFormula) { throw 'Lost footer' }
            $report+=@{extension=$extension;dates=$dates.Count;footer_row=$footer.Row;formatting=$true;sheets=$book.Worksheets.Count}
            $book.Close($false);$book=$null
        }
        $report|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $Folder 'excel-verification.json') -Encoding UTF8
        Write-Output 'PASS: native XLSX/XLSM preservation, inserted/overlapping dates, formulas, text, formats and footer'
    }
} catch {
    throw "$($_.Exception.Message) at $($_.InvocationInfo.PositionMessage)"
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) { $excel.Quit() }
    $book=$null;$sheet=$null;$coeff=$null;$excel=$null
    [GC]::Collect();[GC]::WaitForPendingFinalizers()
}
