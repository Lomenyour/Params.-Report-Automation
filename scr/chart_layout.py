"""Границы Excel-диаграмм в ячейках, без пересчёта в сантиметры."""
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor


def cell_anchor(column, row, columns, rows):
    """Координаты входа однобазные; правая/нижняя границы исключительные."""
    return TwoCellAnchor(editAs="twoCell",
        _from=AnchorMarker(col=column - 1, row=row - 1),
        to=AnchorMarker(col=column - 1 + columns, row=row - 1 + rows))
