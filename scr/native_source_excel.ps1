# Invoked by source_workbook.py with a JSON file, never interpolated shell text.
param([Parameter(Mandatory=$true)][string]$PlanPath)
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = $null
$book = $null
$original = $null
$warnings = [Collections.Generic.List[string]]::new()
$response = @{error=$null; warnings=@(); formula_columns=0; formula_error_count=0; error_examples=@()}

function Get-Blocks($Numbers) {
    $blocks = [Collections.Generic.List[object]]::new()
    foreach ($number in $Numbers) {
        if ($blocks.Count -gt 0 -and $number -eq $blocks[$blocks.Count-1].last+1) {
            $blocks[$blocks.Count-1].last = [int]$number
        } else { $blocks.Add(@{first=[int]$number;last=[int]$number}) }
    }
    return ,$blocks
}
function Cell-Range($Sheet, [int]$Row1, [int]$Col1, [int]$Row2, [int]$Col2) {
    return ,$Sheet.Range($Sheet.Cells.Item($Row1,$Col1),$Sheet.Cells.Item($Row2,$Col2))
}
function Is-Formula($Value) { return $Value -is [string] -and $Value.StartsWith('=') }
function Set-Values($Range, $Values) {
    $Range.Value2=[object[,]]$Values
}

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3 # Preserve VBA but do not execute workbook macros.
    # Automation does not reliably load the user's enabled Excel add-ins. Load
    # only already installed/enabled add-ins, respecting Excel's trust settings.
    foreach ($addin in $excel.AddIns) {
        if (-not $addin.Installed) { continue }
        try {
            if ([IO.Path]::GetExtension($addin.FullName) -ieq '.xll') {
                if (-not $excel.RegisterXLL($addin.FullName)) {
                    $warnings.Add('Не удалось загрузить включённую надстройку: '+$addin.Name)
                }
            } else {
                $excel.AutomationSecurity=2
                $null=$excel.Workbooks.Open($addin.FullName,0,$true)
            }
        } catch { $warnings.Add('Не удалось загрузить включённую надстройку: '+$addin.Name) }
        finally { $excel.AutomationSecurity=3 }
    }
    $original = $excel.Workbooks.Open($plan.input, 0, $true)
    if ($original.Worksheets.Item(1).Name -cne 'Данные') {
        throw 'Первый лист исходной книги должен называться «Данные».'
    }
    $originalCalculation=$excel.Calculation
    $excel.Calculation = -4135 # Manual while copying/inserting; own Excel instance only.
    $excel.CalculateBeforeSave = $false
    $original.SaveCopyAs($plan.output)
    $original.Close($false)
    $original = $null
    $book = $excel.Workbooks.Open($plan.output, 0, $false)
    if ($book.ReadOnly) { throw 'Excel открыл копию только для чтения.' }
    $sheet = $book.Worksheets.Item(1)
    if ($sheet.ProtectContents) { throw 'Лист «Данные» защищён от изменения.' }
    $lastColumn = [int]$plan.last_column
    $lastRow = [int]$plan.last_row
    $firstRow = [int]$plan.first_row
    if ($sheet.ListObjects.Count -gt 0) {
        throw 'На листе «Данные» есть умная таблица Excel. Её продление пока не поддерживается.'
    }
    # Keep references to the original formula cells. Excel adjusts those cells
    # and their absolute/cross-sheet references when rows are inserted.
    $templates = @{}
    $sampleStart = [Math]::Max($firstRow, $lastRow-47)
    $sample = (Cell-Range $sheet $sampleStart 1 $lastRow $lastColumn).FormulaR1C1
    for ($column=1; $column -le $lastColumn; $column++) {
        if ($column -eq $plan.date_column -or $column -in $plan.columns) { continue }
        $formulaRow = $null
        for ($row=$lastRow; $row -ge $sampleStart; $row--) {
            if (Is-Formula $sample.GetValue($row-$sampleStart+1,$column)) {
                $formulaRow = $row
                break
            }
        }
        if ($null -eq $formulaRow) { continue }
        $step = 1
        $alternating = $lastRow-$sampleStart -ge 3
        for ($row=[Math]::Max($sampleStart,$lastRow-5); $row -le $lastRow; $row++) {
            $present = Is-Formula $sample.GetValue($row-$sampleStart+1,$column)
            if ($present -ne (($row % 2) -eq ($formulaRow % 2))) { $alternating=$false }
        }
        if ($alternating) { $step=2 }
        if ($lastRow-$formulaRow -gt 1) {
            $warnings.Add("В колонке $column формула заканчивается раньше последних строк; продление пропущено.")
            continue
        }
        $cell = $sheet.Cells.Item($formulaRow,$column)
        $isArray=[bool]$cell.HasArray
        if ($isArray -and $cell.CurrentArray.CountLarge -gt 1 -and @($plan.new_rows).Count -gt 0) {
            throw "В колонке $column найден многоячеечный массив. Его границы нельзя продлить автоматически."
        }
        $templates[$column] = @{cell=$cell;step=$step;phase=$formulaRow % $step;array=$isArray}
    }
    if (@($plan.new_rows).Count -gt 0 -and $templates.Count -eq 0) {
        throw 'В исходной книге нет построчных формул для продления. Выберите оригинал с формулами, а не экспорт значений.'
    }
    foreach ($insert in @($plan.inserts | Sort-Object before -Descending)) {
        $before=[int]$insert.before
        $end=$before+[int]$insert.count-1
        $null=(Cell-Range $sheet $before 1 $end 1).EntireRow.Insert(-4121)
    }
    foreach ($template in $templates.Values) {
        $template.phase=$template.cell.Row % $template.step
    }
    $finalLast=$lastRow+@($plan.new_rows).Count
    if ($finalLast -gt $sheet.Rows.Count) { throw 'Превышено число строк формата Excel.' }
    $originalLast=[int]$plan.original_rows[-1]
    $newBlocks=Get-Blocks $plan.new_rows
    foreach ($block in $newBlocks) {
        # Copy directly to the range, not through the user's clipboard. Clear
        # contents so unprovided measurements cannot repeat the preceding row.
        $sourceRow=if ($block.first -gt $firstRow) { $block.first-1 } else { [int]$plan.original_rows[0] }
        $destination=Cell-Range $sheet $block.first 1 $block.last $lastColumn
        (Cell-Range $sheet $sourceRow 1 $sourceRow $lastColumn).Copy($destination)
        $null=$destination.ClearContents()
        $destination.RowHeight=$sheet.Rows.Item($sourceRow).RowHeight
        foreach ($column in $templates.Keys) {
            $template=$templates[$column]
            $formula=$template.cell.FormulaR1C1
            $range=Cell-Range $sheet $block.first $column $block.last $column
            if ($template.array -and $template.step -eq 1) {
                $template.cell.Copy($range)
            }
            elseif ($template.step -eq 1) { $range.FormulaR1C1=[string]$formula }
            else {
                if ($template.array) {
                    for ($row=$block.first; $row -le $block.last; $row++) {
                        if (($row % $template.step) -eq $template.phase) {
                            $template.cell.Copy($sheet.Cells.Item($row,$column))
                        }
                    }
                    continue
                }
                $grid=New-Object 'object[,]' ($block.last-$block.first+1),1
                for ($row=$block.first; $row -le $block.last; $row++) {
                    if (($row % $template.step) -eq $template.phase) {
                        $grid.SetValue($formula,$row-$block.first,0)
                    }
                }
                $range.FormulaR1C1=[object[,]]$grid
            }
        }
        foreach ($column in $plan.carry_columns) {
            if ($templates.ContainsKey([int]$column)) { continue }
            $value=$sheet.Cells.Item($originalLast,[int]$column).Value2
            if ($null -ne $value) {
                if ($value -is [string]) { $value="'"+$value }
                $range=Cell-Range $sheet $block.first $column $block.last $column
                if ($value -is [string]) { $range.Value2=[string]$value }
                elseif ($value -is [bool]) { $range.Value2=[bool]$value }
                else { $range.Value2=[double]$value }
            }
        }
        if ($null -ne $plan.hours_column -and -not $templates.ContainsKey([int]$plan.hours_column)) {
            $hours=[int]$plan.hours_column
            if ($block.first -gt $firstRow) {
                (Cell-Range $sheet $block.first $hours $block.last $hours).FormulaR1C1='=R[-1]C+0.5'
            } else {
                $anchor=[int]$plan.original_rows[0]
                for ($row=$block.first; $row -le $block.last; $row++) {
                    $sheet.Cells.Item($row,$hours).FormulaR1C1="=R[$($anchor-$row)]C-$([string](($anchor-$row)/2))".Replace(',','.')
                }
            }
        }
    }
    foreach ($header in $plan.headers) {
        $sheet.Cells.Item([int]$plan.header_row,[int]$header.column).Value2=[string]("'"+$header.label)
    }
    $byRow=@{}
    foreach ($change in $plan.changes) { $byRow[[int]$change.row]=$change }
    $changeBlocks=Get-Blocks @($plan.changes | ForEach-Object { [int]$_.row } | Sort-Object)
    $dateOffset=if ($book.Date1904) { 1462 } else { 0 }
    foreach ($block in $newBlocks) {
        $dateValues=New-Object 'object[,]' ($block.last-$block.first+1),1
        for ($row=$block.first; $row -le $block.last; $row++) {
            $dateValues.SetValue([double]($byRow[$row].date-$dateOffset),$row-$block.first,0)
        }
        Set-Values (Cell-Range $sheet $block.first $plan.date_column $block.last $plan.date_column) $dateValues
    }
    foreach ($block in $changeBlocks) {
        # COM range assignment is batched by column, never one call per sensor.
        for ($part=$block.first; $part -le $block.last; $part+=2000) {
            $end=[Math]::Min($part+1999,$block.last)
            for ($index=0; $index -lt @($plan.columns).Count; $index++) {
                $values=New-Object 'object[,]' ($end-$part+1),1
                for ($row=$part; $row -le $end; $row++) {
                    $value=$byRow[$row].values[$index]
                    if ($value -is [string]) { $value="'"+$value }
                    $values.SetValue($value,$row-$part,0)
                }
                Set-Values (Cell-Range $sheet $part $plan.columns[$index] $end $plan.columns[$index]) $values
            }
        }
    }
    $excel.CalculateFull()
    $errors=[Collections.Generic.List[string]]::new()
    $missingCoolProp=$false
    foreach ($block in $changeBlocks) {
        $range=Cell-Range $sheet $block.first 1 $block.last $lastColumn
        try { $failed=$range.SpecialCells(-4123,16) } catch { $failed=$null }
        if ($null -ne $failed) {
            $response.formula_error_count += [int]$failed.CountLarge
            foreach ($cell in $failed.Cells) {
                if ($cell.Text -match '^#(NAME\?|ИМЯ\?)' -and $cell.Formula -match '(?i)(HA)?PropsSI') {
                    $missingCoolProp=$true
                }
                if ($errors.Count -ge 12) { break }
                $errors.Add($cell.Address($false,$false)+': '+$cell.Text)
            }
        }
    }
    $response.error_examples=@($errors)
    if ($response.formula_error_count -gt 0) {
        $warnings.Add("Excel сохранил ошибки формул в обновлённых строках ($($response.formula_error_count)): $($errors -join '; '). Проверьте исходные формулы, пропуски и надстройки Excel.")
    }
    if ($missingCoolProp) {
        $warnings.Add('Функции PropsSI/HAPropsSI недоступны: для этих исходных формул нужна включённая надстройка CoolProp в Excel. Формулы сохранены.')
    }
    $response.formula_columns=$templates.Count
    $excel.Calculation=$originalCalculation
    $book.Save()
    $book.Close($false)
    $book=$null
} catch {
    $response.error=$_.Exception.Message + ' (строка ' + $_.InvocationInfo.ScriptLineNumber + ')'
} finally {
    if ($null -ne $original) { try { $original.Close($false) } catch {} }
    if ($null -ne $book) { try { $book.Close($false) } catch {} }
    if ($null -ne $excel) { try { $excel.Quit() } catch {} }
    $templates=$null; $sheet=$null; $cell=$null; $range=$null; $sample=$null
    $book=$null; $original=$null; $excel=$null
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    $response.warnings=@($warnings)
    $response | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $plan.result -Encoding UTF8
}
if ($response.error) { exit 1 }
