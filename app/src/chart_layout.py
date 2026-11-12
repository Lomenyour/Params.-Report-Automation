"""Границы Excel-диаграмм в ячейках, без пересчёта в сантиметры."""
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.utils import get_column_letter


def cell_size_points(sheet, column, row, columns, rows):
    """Размер той же ячеечной области для компоновки текстовых блоков."""
    width = 0.
    for index in range(column, column + columns):
        dimension = sheet.column_dimensions.get(get_column_letter(index))
        characters = dimension.width if dimension is not None else (sheet.sheet_format.defaultColWidth or 8.43)
        width += (int(characters * 7 + .5) + 5) * .75
    height = sum((sheet.row_dimensions.get(index).height if sheet.row_dimensions.get(index) is not None else None)
                 or sheet.sheet_format.defaultRowHeight or 15 for index in range(row, row + rows))
    return width, height


def cell_anchor(column, row, columns, rows):
    """Координаты входа однобазные; правая/нижняя границы исключительные."""
    return TwoCellAnchor(editAs="twoCell",
        _from=AnchorMarker(col=column - 1, row=row - 1),
        to=AnchorMarker(col=column - 1 + columns, row=row - 1 + rows))
