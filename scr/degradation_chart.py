"""Редактируемая диаграмма деградации на листе «Графики»."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines, NumericAxis
from openpyxl.chart.data_source import NumData, NumVal
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.legend import LegendEntry
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.chart.trendline import Trendline
from openpyxl.cell import WriteOnlyCell
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import (
    CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties,
    RichTextProperties,
)
from openpyxl.utils.datetime import to_excel
from openpyxl.styles import Alignment, Font, PatternFill
from chart_text import FONT_SIZE, rich_text, label_series

from RH_raschet import _dominant_vna_interval


DATA_SHEET_NAME = "Данные деградации ГТУ"
DATA_COLUMNS = (
    ("date", "Дата"), ("power", "Nприв, МВт"),
    ("fuel_specific", "bприв, нм³/МВт·ч"), ("eta_gtu", "ηГТУ, %"),
    ("vna", "ВНА, %"), ("excel_row", "Строка исходного Excel"),
)
METRICS = (
    ("power", "Nприв, МВт", "C00000"),
    ("fuel_specific", "bприв", "ED7D31"),
    ("eta_gtu", "ηГТУ, %", "7030A0"),
    ("vna", "ВНА, %", "00A6D6"),
)


@dataclass
class DegradationPlot:
    points: pd.DataFrame
    periods: list[dict]


def prepare_degradation_plot(
    values: pd.DataFrame | None,
    periods: pd.DataFrame | None,
    delta_table: pd.DataFrame | None,
) -> DegradationPlot | None:
    """Выбирает те же одноградусные интервалы ВНА, что и регрессия."""
    if values is None or values.empty or periods is None or periods.empty:
        return None

    saved_intervals = (
        delta_table.attrs.get("vna_intervals", {})
        if delta_table is not None else {}
    )
    selected_parts = []
    descriptions = []

    for row in periods.itertuples(index=False):
        number = int(row.period)
        if "period" in values.columns:
            period_data = values.loc[values["period"] == number]
        else:
            dates = pd.to_datetime(values["date"], errors="coerce")
            period_data = values.loc[
                (dates >= row.date_start) & (dates <= row.date_end)
            ]
        if period_data.empty:
            continue

        interval = saved_intervals.get(number)
        if interval is None:
            interval = _dominant_vna_interval(period_data)
        if interval is None:
            continue

        lower, upper, _ = interval
        vna = pd.to_numeric(period_data["vna"], errors="coerce")
        selected = period_data.loc[(vna >= lower) & (vna < upper)].copy()
        selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
        selected = selected.loc[selected["date"].notna()]
        if selected.empty:
            continue
        for key, _, _ in METRICS:
            if key not in selected.columns:
                selected[key] = np.nan
            selected[key] = pd.to_numeric(selected[key], errors="coerce")
            selected.loc[~np.isfinite(selected[key]), key] = np.nan
        selected.loc[selected["eta_gtu"] <= 0, "eta_gtu"] = np.nan
        selected["period"] = number
        if "excel_row" not in selected:
            selected["excel_row"] = np.nan
        selected_parts.append(
            selected[["period"] + [key for key, _ in DATA_COLUMNS]]
        )

        delta = None
        if delta_table is not None and not delta_table.empty:
            match = delta_table.loc[delta_table["Период"] == number]
            if not match.empty:
                delta = match.iloc[0]
        descriptions.append({
            "period": number,
            "date_start": pd.Timestamp(row.date_start),
            "date_end": pd.Timestamp(row.date_end),
            "vna_start": float(lower),
            "vna_end": float(upper),
            "count": len(selected),
            "points_start": selected["date"].min(),
            "points_end": selected["date"].max(),
            "levels": {key: _finite(selected[key].median()) for key, _, _ in METRICS},
            "delta_n": _finite(delta.get("ΔNприв")) if delta is not None else None,
            "delta_b": _finite(delta.get("Δbприв")) if delta is not None else None,
            "delta_eta": _finite(delta.get("Δη, п.п.")) if delta is not None else None,
        })

    if not selected_parts:
        return None
    points = pd.concat(selected_parts, ignore_index=True)
    points = points.sort_values("date", kind="stable").reset_index(drop=True)
    return DegradationPlot(points, descriptions)


def _finite(value):
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) and np.isfinite(parsed) else None


def _cache(values, *, dates=False):
    points = []
    for index, value in enumerate(values):
        if pd.isna(value):
            continue
        number = (
            to_excel(pd.Timestamp(value).to_pydatetime())
            if dates else _finite(value)
        )
        if number is not None:
            points.append(NumVal(idx=index, v=float(number)))
    return NumData(
        formatCode="dd.mm.yyyy" if dates else "General",
        ptCount=len(values), pt=points,
    )


def _write_data_blocks(book, plot):
    """Сохраняет точки каждого периода без округления на видимом листе."""
    sheet = book.create_sheet(DATA_SHEET_NAME)
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A6"
    for index, width in enumerate((24, 21, 27, 19, 17, 26), start=1):
        sheet.column_dimensions[_col(index)].width = width

    def cell(value, *, header=False):
        if pd.isna(value):
            value = None
        elif isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()
        elif isinstance(value, np.generic):
            value = value.item()
        item = WriteOnlyCell(sheet, value=value)
        item.font = Font(name="Calibri", size=11, bold=header,
                         color="FFFFFF" if header else "000000")
        item.alignment = Alignment(vertical="center", wrap_text=True)
        if header:
            item.fill = PatternFill("solid", fgColor="24476A")
        return item

    blocks = {}
    offset = 0
    for period in plot.periods:
        number = period["period"]
        points = plot.points.loc[plot.points["period"] == number]
        sheet.row_dimensions[offset + 1].height = 26
        sheet.row_dimensions[offset + 2].height = 30
        sheet.merged_cells.add(f"A{offset + 1}:F{offset + 1}")
        sheet.merged_cells.add(f"A{offset + 2}:F{offset + 2}")
        sheet.append([cell(f"Период {number}. Данные общей деградации ГТУ")])
        sheet.append([cell(
            f"{period['date_start']:%d.%m.%Y %H:%M} – {period['date_end']:%d.%m.%Y %H:%M}; "
            f"{period['vna_start']:g} % ≤ ВНА < {period['vna_end']:g} %"
        )])
        sheet.append([cell(f"Точек: {len(points)}")])
        sheet.append([])
        sheet.append([cell(title, header=True) for _, title in DATA_COLUMNS])
        first = offset + 6
        for record in points.to_dict("records"):
            row = []
            for key, _ in DATA_COLUMNS:
                item = cell(record[key])
                item.number_format = "dd.mm.yyyy hh:mm" if key == "date" else (
                    "0" if key == "excel_row" else "0.000"
                )
                row.append(item)
            sheet.append(row)
        blocks[number] = (points, first)
        sheet.append([])
        sheet.append([])
        offset += len(points) + 7
    return sheet, blocks


def _series(sheet, points, first, key, title, color, period) -> Series:
    last = first + len(points) - 1
    column = [name for name, _ in DATA_COLUMNS].index(key) + 1
    x = Reference(sheet, min_col=1, min_row=first, max_row=last)
    y = Reference(sheet, min_col=column, min_row=first, max_row=last)
    series = Series(y, x, title=title)
    series.xVal.numRef.numCache = _cache(points["date"], dates=True)
    series.yVal.numRef.numCache = _cache(points[key])
    series.graphicalProperties.line.noFill = True
    series.marker.symbol = "circle"
    series.marker.size = 2
    series.marker.graphicalProperties.solidFill = color
    series.marker.graphicalProperties.line.solidFill = color
    series.smooth = False
    valid = points[key].notna()
    if valid.sum() >= 2 and points.loc[valid, "date"].nunique() >= 2:
        series.trendline = Trendline(
            trendlineType="linear", name=f"Линейная ({title}, период {period})",
            dispEq=False, dispRSqr=False,
        )
        series.trendline.spPr = GraphicalProperties(
            ln=LineProperties(solidFill=color, w=25400),
        )
    return series


def _text(size=FONT_SIZE, bold=False):
    return RichText(
        bodyPr=RichTextProperties(lIns=45000, rIns=45000, tIns=35000, bIns=35000),
        p=[Paragraph(r=[], pPr=ParagraphProperties(
            defRPr=CharacterProperties(
                sz=size, b=bold, solidFill="000000",
                latin=DrawingFont(typeface="Times New Roman"),
            ),
        ), endParaRPr=CharacterProperties(lang="ru-RU"))],
    )


def _grid(color, width):
    return ChartLines(spPr=GraphicalProperties(
        ln=LineProperties(solidFill=color, w=width),
    ))


def _axis_title(axis, title):
    axis.title = title
    axis.title.txPr = _text(bold=True)
    axis.title.tx.rich = rich_text(title, bold=True)


def _summary_cells(sheet, plot: DegradationPlot, start_row: int, start_col: int):
    """Подписи интервалов и величины для визуальной проверки графика."""
    offset = start_col - 1
    cells = {start_row: {start_col: (
        "ДЕГРАДАЦИЯ ГТУ — точки в самом частом интервале ВНА каждого периода",
        "period",
    )}}
    sheet.merged_cells.add(
        f"{_col(start_col)}{start_row}:{_col(start_col + 22)}{start_row}"
    )
    sheet.row_dimensions[start_row].height = 27

    header_row = start_row + 38
    layout = (
        (1, 3, "Период"),
        (4, 7, "Даты периода"),
        (8, 10, "ВНА-фильтр"),
        (11, 12, "Точек"),
        (13, 14, "ΔN, МВт"),
        (15, 16, "Потеря N"),
        (17, 18, "Δbприв"),
        (19, 20, "Рост b"),
        (21, 23, "Δη, п.п."),
    )
    cells[header_row] = {}
    for first, last, title in layout:
        sheet.merged_cells.add(
            f"{_col(first + offset)}{header_row}:{_col(last + offset)}{header_row}"
        )
        cells[header_row][first + offset] = (title, "header")
    sheet.row_dimensions[header_row].height = 24

    for index, period in enumerate(plot.periods, start=1):
        row = header_row + index
        delta_n = period["delta_n"]
        delta_b = period["delta_b"]
        data = (
            f"Период {period['period']}",
            f"{period['date_start']:%d.%m.%Y} – {period['date_end']:%d.%m.%Y}",
            f"{period['vna_start']:.0f}–{period['vna_end']:.0f} %",
            period["count"],
            delta_n,
            max(-delta_n, 0.0) if delta_n is not None else None,
            delta_b,
            max(delta_b, 0.0) if delta_b is not None else None,
            period["delta_eta"],
        )
        cells[row] = {}
        for (first, last, _), value in zip(layout, data):
            sheet.merged_cells.add(
                f"{_col(first + offset)}{row}:{_col(last + offset)}{row}"
            )
            cells[row][first + offset] = (value, "body")
        sheet.row_dimensions[row].height = 21
    return cells, header_row + len(plot.periods) + 1


def _col(index: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(index)


def _delta_label(symbol, value, unit, *, direction):
    if value is None:
        return f"{symbol} = нет данных"
    arrow = "↑" if direction > 0 else "↓"
    if direction * value <= 0 or round(abs(value), 3) == 0:
        return f"{symbol} = {arrow} отсутствует"
    number = f"{abs(value):.3f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{symbol} = {arrow}{number} {unit}"


def _add_period_labels(chart, secondary, plot):
    placed = []
    span = chart.x_axis.scaling.max - chart.x_axis.scaling.min
    low, high = chart.y_axis.scaling.min, chart.y_axis.scaling.max
    vna_low, vna_high = secondary.y_axis.scaling.min, secondary.y_axis.scaling.max
    for period in plot.periods:
        first = period["points_start"]
        moment = first + (period["points_end"] - first) / 2
        texts = (
            ("fuel_specific", _delta_label("Δbприв", period["delta_b"], "нм³/МВт·ч", direction=1)),
            ("vna", f"{period['vna_start']:.1f} % ≤ ВНА < {period['vna_end']:.1f} %".replace(".", ",")),
            ("power", _delta_label("ΔNприв", period["delta_n"], "МВт", direction=-1)),
            ("eta_gtu", _delta_label("ΔηГТУ", period["delta_eta"], "%", direction=-1)),
        )
        for key, text in texts:
            value = period["levels"][key]
            if value is None:
                continue
            y = ((value - vna_low) / (vna_high - vna_low) if key == "vna"
                 else (value - low) / (high - low))
            offset = {"fuel_specific": .085, "vna": .07, "power": .07, "eta_gtu": .057}[key]
            base = y + offset if y + offset <= .94 else y - offset
            base = min(.94, max(.06, base))
            x = to_excel(moment.to_pydatetime())
            # Короткие соседние периоды: оставляем X над своими данными,
            # но раздвигаем подписи по высоте, не сдвигая сами точки.
            nearby = [py for px, py in placed if abs(x - px) < .20 * span]
            candidates = sorted({base + delta for delta in (0, .07, .14, .21, .28, -.07, -.14, -.21)}
                | {py + delta for py in nearby for delta in (.07, -.07)},
                key=lambda candidate: (candidate < base, abs(candidate - base)))
            y = next((candidate for candidate in candidates if .06 <= candidate <= .94
                and all(abs(x - px) >= .20 * span or abs(candidate - py) >= .055
                        for px, py in placed)), base)
            placed.append((x, y))
            chart.series.append(label_series(moment, low + y * (high - low), text,
                                            dates=True, size=FONT_SIZE, bold=True))


def _main_scale(axis, points):
    values = points[[key for key, _, _ in METRICS[:3]]].to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    low = min(0., float(values.min())) if values.size else 0.
    high = max(350., float(values.max())) if values.size else 350.
    if low == 0 and high == 350:
        axis.scaling.min, axis.scaling.max, axis.majorUnit = 0, 350, 50
    else:
        padding = (high - low) * .05
        low = low - padding if low < 0 else 0
        high = high + padding if high > 350 else 350
        raw_step = (high - low) / 7
        magnitude = 10 ** math.floor(math.log10(raw_step))
        step = next(unit * magnitude for unit in (1, 2, 5, 10)
                    if unit * magnitude >= raw_step)
        axis.scaling.min = math.floor(low / step) * step
        axis.scaling.max = math.ceil(high / step) * step
        axis.majorUnit = step
    axis.minorUnit = axis.majorUnit / 5


def add_degradation_chart(sheet, plot: DegradationPlot,
                          start_row: int, start_col: int = 1):
    """Добавляет нативную XY-диаграмму и возвращает видимые ячейки таблицы."""
    main = ScatterChart()
    main.title = None
    main.roundedCorners = False
    main.graphical_properties = GraphicalProperties(
        solidFill="FFFFFF", ln=LineProperties(noFill=True),
    )
    main.scatterStyle = "marker"
    main.width = 42
    main.height = 18
    main.x_axis.axId = 110
    main.y_axis.axId = 120
    main.x_axis.crossAx = 120
    main.y_axis.crossAx = 110
    main.x_axis.delete = False
    main.y_axis.delete = False
    _axis_title(main.x_axis, "Дата")
    main.x_axis.numFmt = "dd.mm.yyyy"
    main.x_axis.axPos = "b"
    main.x_axis.txPr = _text()
    _axis_title(main.y_axis, "Nприв, МВт; bприв; ηГТУ, %")
    main.y_axis.axPos = "l"
    main.y_axis.txPr = _text()
    _main_scale(main.y_axis, plot.points)
    main.y_axis.numFmt = "0"
    main.y_axis.tickLblPos = "nextTo"
    main.y_axis.majorGridlines = _grid("A6A6A6", 9525)
    main.y_axis.minorGridlines = _grid("D9D9D9", 4762)
    main.x_axis.majorGridlines = _grid("A6A6A6", 9525)
    main.x_axis.minorGridlines = _grid("D9D9D9", 4762)
    main.x_axis.tickLblPos = "low"
    main.y_axis.crosses = "min"
    main.legend.position = "b"
    main.legend.overlay = False
    main.legend.txPr = _text()
    main.legend.layout = Layout(manualLayout=ManualLayout(
        xMode="edge", yMode="edge", x=0.15, y=0.93, w=0.7, h=0.05,
    ))
    main.layout = Layout(manualLayout=ManualLayout(
        layoutTarget="inner", xMode="edge", yMode="edge",
        x=0.075, y=0.035, w=0.845, h=0.80,
    ))
    main.visible_cells_only = False
    main.display_blanks = "gap"

    first_date = plot.points["date"].min()
    last_date = plot.points["date"].max()
    lower_date = first_date.normalize() - pd.DateOffset(months=2)
    upper_date = last_date.normalize() + pd.DateOffset(months=2)
    main.x_axis.scaling.min = to_excel(lower_date.to_pydatetime())
    main.x_axis.scaling.max = to_excel(upper_date.to_pydatetime())
    span = max(1, (upper_date - lower_date).days)
    main.x_axis.majorUnit = next(
        (days for days in (1, 2, 5, 10, 20, 25, 50, 100, 150, 200, 365)
         if days >= span / 6), 365,
    )
    main.x_axis.minorUnit = main.x_axis.majorUnit / 5

    data_sheet, blocks = _write_data_blocks(sheet.parent, plot)
    visible_legend = set()
    for key, title, color in METRICS[:3]:
        first_series = True
        for number, (points, first) in blocks.items():
            if not points[key].notna().any():
                continue
            if first_series:
                visible_legend.add(len(main.series))
                first_series = False
            main.series.append(_series(data_sheet, points, first, key, title, color, number))

    secondary = ScatterChart()
    secondary.scatterStyle = "marker"
    secondary.x_axis = NumericAxis(
        axId=140, crossAx=130, axPos="b", delete=True,
    )
    secondary.x_axis.majorGridlines = None
    secondary.x_axis.minorGridlines = None
    secondary.x_axis.scaling.min = main.x_axis.scaling.min
    secondary.x_axis.scaling.max = main.x_axis.scaling.max
    secondary.y_axis.axId = 130
    secondary.y_axis.crossAx = 140
    secondary.y_axis.axPos = "r"
    secondary.y_axis.delete = False
    _axis_title(secondary.y_axis, "Положение ВНА, %")
    secondary.y_axis.txPr = _text()
    secondary.y_axis.crosses = "max"
    secondary.y_axis.tickLblPos = "nextTo"
    secondary.y_axis.numFmt = "0"
    secondary.y_axis.majorGridlines = None
    secondary.y_axis.minorGridlines = None
    secondary.y_axis.scaling.min = min(65, math.floor(plot.points["vna"].min() / 5) * 5)
    secondary.y_axis.scaling.max = 100
    secondary.y_axis.majorUnit = 5 if secondary.y_axis.scaling.min >= 50 else 10
    secondary.visible_cells_only = False
    for number, (points, first) in blocks.items():
        secondary.series.append(_series(data_sheet, points, first, "vna", "ВНА, %", "00A6D6", number))
    _add_period_labels(main, secondary, plot)
    visible_legend.add(len(main.series))  # Первый ряд ВНА на правой оси.
    main += secondary
    series_count = sum(len(part.series) for part in main._charts)
    trend_count = sum(series.trendline is not None for part in main._charts for series in part.series)
    main.legend.legendEntry = [LegendEntry(idx=index, delete=True)
                              for index in range(series_count + trend_count)
                              if index not in visible_legend]
    sheet.add_chart(main, f"{_col(start_col)}{start_row + 1}")
    return _summary_cells(sheet, plot, start_row, start_col)
