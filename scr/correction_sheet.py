"""Снимок листа поправок: значения, оформление и собственные диаграммы.

Из исходного ZIP изолируется один лист, поэтому миллион строк основного
листа не загружается в объекты openpyxl. Формулы поправок фиксируются по
сохранённым результатам: ссылки на удалённые отчётные листы не переносятся.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass
import io
import json
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import load_workbook
from openpyxl.cell import WriteOnlyCell
import pandas as pd

from gas_passport import MARKER, write_passport

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass(frozen=True)
class CorrectionSheetSnapshot:
    content: bytes


def correction_sheet_from_profile(profile):
    """Миграция старого кеша: используемые числа в тех же ячейках, без выдуманного листа."""
    from openpyxl import Workbook
    import re
    book = Workbook()
    sheet = book.active
    sheet.title = "Поправки"
    sheet["A1"] = "Использованные коэффициенты из ранее сохранённого профиля"
    for cell, value in profile.items():
        if re.fullmatch(r"[A-Z]+[0-9]+", cell):
            sheet[cell] = value
    output = io.BytesIO()
    book.save(output)
    book.close()
    return CorrectionSheetSnapshot(output.getvalue())


def read_correction_sheet(path):
    with ZipFile(path) as source:
        workbook = ET.fromstring(source.read("xl/workbook.xml"))
        sheets = workbook.find(f"{{{NS}}}sheets")
        selected = next((s for s in sheets if s.get("name") == "Поправки"), None)
        if selected is None:
            return None
        relation_id = selected.get(f"{{{REL}}}id")
        relations = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        relation = next(r for r in relations if r.get("Id") == relation_id)
        target = relation.get("Target")
        sheet_path = target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target)
        for sheet in list(sheets):
            if sheet is not selected:
                sheets.remove(sheet)
        names = workbook.find(f"{{{NS}}}definedNames")
        if names is not None:
            workbook.remove(names)
        views = workbook.find(f"{{{NS}}}bookViews")
        if views is not None:
            for view in views:
                view.set("activeTab", "0")
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as isolated:
            for name in source.namelist():
                if name.startswith("xl/worksheets/") and name.endswith(".xml") and name != sheet_path:
                    continue
                isolated.writestr(name, ET.tostring(workbook) if name == "xl/workbook.xml" else source.read(name))
    with pd.ExcelFile(path, engine="calamine") as book:
        cached = book.parse("Поправки", header=None)
    book = load_workbook(io.BytesIO(output.getvalue()), keep_links=False)
    sheet = book["Поправки"]
    # Удаляем прежний блок паспорта, его заменит фактически использованный.
    start = next((cell.row for cell in list(sheet._cells.values()) if cell.column == 1 and cell.value == MARKER), None)
    if start:
        data = json.loads(sheet.cell(start, 2).value)
        count = 10 + len(data.get("components", {}))
        end = start + count - 1
        # Пользовательские записи ниже/правее нашего блока не удаляются.
        has_extra = any(cell.value is not None and (cell.row > end or
                        start <= cell.row <= end and cell.column > 3)
                        for cell in list(sheet._cells.values()))
        if not has_extra:
            sheet.delete_rows(start, sheet.max_row - start + 1)
        else:
            from openpyxl.styles import Font, PatternFill
            for row in sheet.iter_rows(min_row=start, max_row=end, max_col=3):
                for cell in row:
                    cell.value = None
                    cell.font, cell.fill = Font(), PatternFill()
    for cell in list(sheet._cells.values()):
        if cell.data_type == "f":
            value = cached.iat[cell.row - 1, cell.column - 1] if (
                cell.row <= len(cached) and cell.column <= len(cached.columns)) else None
            cell.value = None if value is None or pd.isna(value) else value
    snapshot = io.BytesIO()
    book.save(snapshot)
    book.close()
    return CorrectionSheetSnapshot(snapshot.getvalue())


def write_correction_sheet(book, snapshot, passport=None):
    if snapshot is None and passport is None:
        return
    target = book.create_sheet("Поправки")
    if snapshot is not None:
        source_book = load_workbook(io.BytesIO(snapshot.content), keep_links=False)
        try:
            source = source_book["Поправки"]
            for name in ("sheet_format", "sheet_properties", "sheet_state", "sheet_view",
                         "sheet_protection", "page_setup", "page_margins", "print_options"):
                # sheet_view/protection имеют особые имена в openpyxl.
                if name in ("sheet_view", "sheet_protection"):
                    continue
                if hasattr(source, name):
                    setattr(target, name, copy(getattr(source, name)))
            target.views = deepcopy(source.views)
            target.protection = copy(source.protection)
            target.freeze_panes = source.freeze_panes
            target.auto_filter = deepcopy(source.auto_filter)
            target.conditional_formatting = deepcopy(source.conditional_formatting)
            target.data_validations = deepcopy(source.data_validations)
            target.print_options = copy(source.print_options)
            if source.print_area:
                target.print_area = str(source.print_area)
            target.print_title_rows = source.print_title_rows
            target.print_title_cols = source.print_title_cols
            for key, value in source.column_dimensions.items():
                target.column_dimensions[key] = copy(value)
            for key, value in source.row_dimensions.items():
                target.row_dimensions[key] = copy(value)
            if passport is not None:
                target.row_dimensions[source.max_row + 3].hidden = True
            for merged in source.merged_cells.ranges:
                target.merged_cells.add(str(merged))
            for row in source:
                cells = []
                for original in row:
                    if original.value is None and not original.has_style and not original.comment and not original.hyperlink:
                        cells.append(None)
                        continue
                    cell = WriteOnlyCell(target, original.value)
                    for attr in ("font", "fill", "border", "alignment", "protection", "number_format"):
                        setattr(cell, attr, copy(getattr(original, attr)))
                    if original.comment:
                        cell.comment = copy(original.comment)
                    if original.hyperlink:
                        cell.hyperlink = copy(original.hyperlink)
                    if original.data_type == "s":
                        cell.data_type = "s"
                    cells.append(cell)
                target.append(cells)
            for chart in source._charts:
                target.add_chart(deepcopy(chart))
            # Изображения уже загружены openpyxl из изолированной книги.
            for picture in source._images:
                target.add_image(deepcopy(picture))
        finally:
            source_book.close()
    if passport is not None:
        if snapshot is None:
            target.row_dimensions[3].hidden = True
        target.append([])
        target.append([])
        write_passport(target, passport)
