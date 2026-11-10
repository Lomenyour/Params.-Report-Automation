"""Update a full copy of the input workbook using installed Microsoft Excel.

Only measurement import is shared with the analytical workflow. No regression,
period detection, economics or Python formula evaluation runs here.
"""
from __future__ import annotations

from bisect import bisect_left
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

import pandas as pd
from openpyxl.utils import column_index_from_string

from data_assembly import assemble_sensor_data
from workbook_profile import read_layout


def validate_destination(book, source, destination):
    book, source, destination = map(lambda value: Path(value).resolve(), (book, source, destination))
    if destination in (book, source) or any(
        destination.exists() and os.path.samefile(destination, item) for item in (book, source)
    ):
        raise ValueError('Выберите отдельный файл: исходную книгу и выгрузку перезаписывать нельзя.')
    if destination.suffix.lower() != book.suffix.lower():
        raise ValueError(f'Сохраните исходный формат книги: {book.suffix}.')
    if book.suffix.lower() not in ('.xlsx', '.xlsm', '.xlsb', '.xls'):
        raise ValueError('Поддерживаются книги .xlsx, .xlsm, .xlsb и .xls.')
    return destination


def _scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def prepare_source_update(book, source, sheet, mappings, *, setup, station_id, unit, repository):
    """Build a physical-row plan; the original workbook remains untouched."""
    book, source = Path(book).resolve(), Path(source).resolve()
    stat = book.stat()
    if tuple(setup.stamp) != (str(book), stat.st_mtime_ns, stat.st_size):
        raise ValueError('Исходная книга изменилась. Повторно подтвердите её параметры.')
    source_stat = source.stat()
    layout = read_layout(book)
    date_column = setup.bindings['date']['column']
    dates = pd.to_datetime(layout.values[date_column], errors='coerce')
    valid = dates.dropna()
    if valid.empty:
        raise ValueError('На первом листе «Данные» нет датированных строк для продления.')
    if valid.dt.tz is not None:
        raise ValueError('Время книги должно быть локальным, без часового пояса, как в выгрузке.')
    rounded = valid.dt.round('min')
    if ((valid - rounded).abs() > pd.Timedelta(seconds=1)).any():
        raise ValueError('Время основной книги смещено от целой минуты больше чем на секунду.')
    if rounded.duplicated().any() or not rounded.is_monotonic_increasing:
        raise ValueError('Даты основной книги должны идти по возрастанию без повторов.')
    first, last = int(valid.index[0]), int(valid.index[-1])
    if len(valid) != last - first + 1:
        raise ValueError('Внутри данных есть строки без даты. Уточните их перед продлением книги.')
    if ((rounded.dt.minute % 30 != 0) | (rounded.dt.second != 0)).any():
        raise ValueError('Исходная книга должна содержать получасовые метки :00 и :30.')
    assembled = assemble_sensor_data(book, source, sheet, mappings, station_id=station_id,
                                    unit=unit, repository=repository, book_setup=setup)
    original = list(pd.DatetimeIndex(rounded))
    changed = pd.DatetimeIndex(assembled.changed_dates)
    all_dates = sorted(set(original) | set(changed))
    body_start = setup.header_row + 2 + first
    original_set = set(original)
    new_dates = [date for date in all_dates if date not in original_set]
    inserts = []
    for date in new_dates:
        before = body_start + bisect_left(original, date)
        if inserts and inserts[-1]['before'] == before:
            inserts[-1]['count'] += 1
        else:
            inserts.append(dict(before=before, count=1))
    rows_by_date = {date: body_start + index for index, date in enumerate(all_dates)}
    columns = []
    headers = []
    for mapping in mappings:
        if mapping.status == 'ignored':
            continue
        if mapping.status == 'deferred':
            target = next(column for column, label in assembled.headers.items()
                          if label == f'До уточнения: {mapping.source}')
            headers.append(dict(column=column_index_from_string(target), label=assembled.headers[target]))
        else:
            target = mapping.target
        if target not in columns:
            columns.append(target)
    if not columns:
        raise ValueError('Нет каналов для вставки: все соответствия отмечены «Игнорировать».')
    if date_column in columns or setup.bindings.get('hours_input', {}).get('column') in columns:
        raise ValueError('Измерениями нельзя перезаписывать дату или наработку.')
    changes = [dict(row=rows_by_date[date], date=(date.to_pydatetime() - pd.Timestamp('1899-12-30').to_pydatetime()).total_seconds()/86400,
                    values=[_scalar(assembled.values.at[date, column]) for column in columns])
               for date in changed]
    # Excel receives only mapped channels. Existing raw/derived columns outside
    # this set are never replaced by the merged frame's synthetic hour counter.
    metadata = {row['column']: row for row in setup.columns}
    carry = [column_index_from_string(column) for column, row in metadata.items()
             if (row.get('kind') == 'computed' or row.get('role') in
                 ('gas_density', 'gas_c_h', 'gas_q_mass', 'q_lower'))
             and column not in columns and row.get('role') not in ('date', 'hours_input')]
    return dict(input=str(book), source=str(source), input_stamp=[stat.st_mtime_ns, stat.st_size],
                source_stamp=[source_stat.st_mtime_ns, source_stat.st_size],
                date_column=column_index_from_string(date_column),
                hours_column=column_index_from_string(setup.bindings['hours_input']['column'])
                    if 'hours_input' in setup.bindings else None,
                first_row=body_start, last_row=body_start + len(original)-1,
                original_rows=[rows_by_date[date] for date in original],
                new_rows=[rows_by_date[date] for date in new_dates],
                inserts=inserts, changes=changes,
                columns=[column_index_from_string(column) for column in columns],
                carry_columns=carry, headers=headers,
                last_column=max(column_index_from_string(column) for column in assembled.headers),
                header_row=setup.header_row+1, imported_rows=assembled.imported_rows,
                overlap_rows=assembled.overlap_rows, added_rows=len(new_dates),
                unmapped_measured=[row.get('header') or column for column, row in metadata.items()
                    if row.get('kind') == 'measured' and column not in columns
                    and column_index_from_string(column) not in carry],
                invalid_sensor_values=assembled.invalid_sensor_values,
                diagnostics=assembled.source_diagnostics)


def save_source_workbook(book, source, sheet, mappings, destination, *, setup, station_id,
                         unit, repository, log=lambda text: None):
    destination = validate_destination(book, source, destination)
    log('Проверка дат и соответствий; получасовой отбор выгрузки.\n')
    plan = prepare_source_update(book, source, sheet, mappings, setup=setup,
                                 station_id=station_id, unit=unit, repository=repository)
    log(f"Получасовых строк: {plan['imported_rows']}; совпало дат: {plan['overlap_rows']}; "
        f"новых строк: {plan['added_rows']}. Часовой пояс не преобразуется.\n")
    diagnostics = plan.get('diagnostics') or {}
    log(f"Пропущено строк выгрузки: {diagnostics.get('skipped_rows', 0)}, "
        f"из них без распознанной даты: {diagnostics.get('invalid_dates', 0)}.\n")
    for mapping in mappings:
        if mapping.status == 'mapped' and (mapping.factor != 1 or mapping.offset != 0):
            log(f'Единицы {mapping.source} → {mapping.target}: ×{mapping.factor:.12g}'
                f' + ({mapping.offset:.12g}); {mapping.source_unit} → {mapping.target_unit}.\n')
    if plan['invalid_sensor_values']:
        log(f"Нечисловые показания сохраняются без замены нулями: {plan['invalid_sensor_values']}\n")
    if plan['added_rows'] and plan['unmapped_measured']:
        log('Измерения без назначения остаются пустыми в новых строках: '
            + '; '.join(plan['unmapped_measured']) + '\n')
    log('Открытие отдельного Excel: копирование всех листов, вставка данных и продление формул.\n')
    log('Коэффициенты и паспортные значения продолжаются из исходной книги.\n')
    # Staging in the output directory allows atomic publication after Excel has
    # closed the copy. A failed COM run cannot damage an existing destination.
    with tempfile.TemporaryDirectory(prefix='.gtu-source-', dir=destination.parent) as folder:
        temporary = Path(folder)
        plan['output'] = str(temporary / ('book' + destination.suffix))
        plan['result'] = str(temporary / 'result.json')
        plan_path = temporary / 'plan.json'
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, allow_nan=False), encoding='utf-8-sig')
        worker = Path(__file__).with_name('native_source_excel.ps1')
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                   'Bypass', '-File', str(worker), '-PlanPath', str(plan_path)]
        result = subprocess.run(command, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                check=False)
        response_path = Path(plan['result'])
        response = json.loads(response_path.read_text(encoding='utf-8-sig')) if response_path.exists() else {}
        if result.returncode or response.get('error') or not Path(plan['output']).is_file():
            raise RuntimeError(response.get('error') or 'Excel не сохранил копию. Проверьте установку Excel.')
        for key, path in (('input_stamp', Path(book)), ('source_stamp', Path(source))):
            stat = path.stat()
            if plan[key] != [stat.st_mtime_ns, stat.st_size]:
                raise RuntimeError('Один из входных файлов изменился во время сохранения. Повторите операцию.')
        os.replace(plan['output'], destination)
    for warning in response.get('warnings', []):
        log(f'Внимание: {warning}\n')
    log(f"Excel продлил формулы в {response['formula_columns']} колонках. "
        f"Ошибок формул в обновлённых строках: {response['formula_error_count']}.\n")
    return response
