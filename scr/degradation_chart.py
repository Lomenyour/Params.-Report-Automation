"""Редактируемая диаграмма деградации на листе «Графики»."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import NumericAxis
from openpyxl.chart.data_source import NumData, NumVal
from openpyxl.utils.datetime import to_excel

from RH_raschet import _dominant_vna_interval


HELPER_COLUMN = 39  # AM:AQ; не пересекается с диапазонами диаграммы перепадов.
HELPER_HEADERS = ("Дата", "Nприв, МВт", "bприв", "ηГТУ, %", "ВНА, %")
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
        selected_parts.append(
            selected[["date", "power", "fuel_specific", "eta_gtu", "vna"]]
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


def _series(sheet, plot: DegradationPlot, key: str, title: str,
            color: str, column: int) -> Series:
    last = len(plot.points) + 1
    x = Reference(sheet, min_col=HELPER_COLUMN, min_row=2, max_row=last)
    y = Reference(sheet, min_col=column, min_row=2, max_row=last)
    series = Series(y, x, title=title)
    series.xVal.numRef.numCache = _cache(plot.points["date"], dates=True)
    series.yVal.numRef.numCache = _cache(plot.points[key])
    series.graphicalProperties.line.noFill = True
    series.marker.symbol = "circle"
    series.marker.size = 2
    series.marker.graphicalProperties.solidFill = color
    series.marker.graphicalProperties.line.solidFill = color
    return series


def _summary_cells(sheet, plot: DegradationPlot, start_row: int):
    """Подписи интервалов и величины для визуальной проверки графика."""
    cells = {start_row: {1: (
        "ДЕГРАДАЦИЯ ГТУ — точки в самом частом интервале ВНА каждого периода",
        "period",
    )}}
    sheet.merged_cells.add(f"A{start_row}:W{start_row}")
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
            f"{_col(first)}{header_row}:{_col(last)}{header_row}"
        )
        cells[header_row][first] = (title, "header")
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
            sheet.merged_cells.add(f"{_col(first)}{row}:{_col(last)}{row}")
            cells[row][first] = (value, "body")
        sheet.row_dimensions[row].height = 21
    return cells, header_row + len(plot.periods) + 1


def _col(index: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(index)


def add_degradation_chart(sheet, plot: DegradationPlot, start_row: int):
    """Добавляет нативную XY-диаграмму и возвращает видимые ячейки таблицы."""
    main = ScatterChart()
    main.title = "Деградация параметров ГТУ"
    main.scatterStyle = "marker"
    main.width = 42
    main.height = 18
    main.x_axis.axId = 110
    main.y_axis.axId = 120
    main.x_axis.crossAx = 120
    main.y_axis.crossAx = 110
    main.x_axis.title = "Дата"
    main.x_axis.numFmt = "dd.mm.yyyy"
    main.x_axis.axPos = "b"
    main.y_axis.title = "Nприв, МВт; bприв; ηГТУ, %"
    main.y_axis.axPos = "l"
    main.y_axis.scaling.min = 0
    maximum = max(
        350.0,
        *(
            float(plot.points[key].max()) * 1.1
            for key in ("power", "fuel_specific", "eta_gtu")
            if plot.points[key].notna().any()
        ),
    )
    main.y_axis.scaling.max = math.ceil(maximum / 50.0) * 50.0
    main.y_axis.majorUnit = 50
    main.y_axis.minorUnit = 10
    main.legend.position = "b"
    main.visible_cells_only = False
    main.display_blanks = "gap"

    first_date = plot.points["date"].min()
    last_date = plot.points["date"].max()
    main.x_axis.scaling.min = to_excel(
        (first_date - pd.Timedelta(days=2)).to_pydatetime()
    )
    main.x_axis.scaling.max = to_excel(
        (last_date + pd.Timedelta(days=2)).to_pydatetime()
    )
    span = max(1, (last_date - first_date).days)
    main.x_axis.majorUnit = max(1, math.ceil(span / 8))

    for offset, (key, title, color) in enumerate(METRICS[:3], start=1):
        main.series.append(_series(
            sheet, plot, key, title, color, HELPER_COLUMN + offset
        ))

    secondary = ScatterChart()
    secondary.scatterStyle = "marker"
    secondary.x_axis = NumericAxis(
        axId=140, crossAx=130, axPos="b", delete=True,
    )
    secondary.x_axis.scaling.min = main.x_axis.scaling.min
    secondary.x_axis.scaling.max = main.x_axis.scaling.max
    secondary.y_axis.axId = 130
    secondary.y_axis.crossAx = 140
    secondary.y_axis.axPos = "r"
    secondary.y_axis.title = "Положение ВНА, %"
    secondary.y_axis.scaling.min = (
        65 if plot.points["vna"].min() >= 65 else 0
    )
    secondary.y_axis.scaling.max = 100
    secondary.y_axis.majorUnit = 5 if secondary.y_axis.scaling.min else 10
    secondary.visible_cells_only = False
    secondary.series.append(_series(
        sheet, plot, "vna", "ВНА, %", "00A6D6", HELPER_COLUMN + 4
    ))
    main += secondary
    sheet.add_chart(main, f"A{start_row + 1}")
    return _summary_cells(sheet, plot, start_row)
