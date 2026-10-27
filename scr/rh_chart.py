"""Одна нативная расходная характеристика на период из существующих кандидатов."""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.data_source import NumData, NumVal
from openpyxl.chart.legend import LegendEntry
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.utils import get_column_letter

from chart_text import rich_text, label_series
from RH_raschet import select_rh_variants, rh_equation


@dataclass
class RHPlot:
    result: dict
    start: pd.DataFrame
    end: pd.DataFrame


def prepare_rh_plots(values, results):
    if values is None or values.empty or not results:
        return []
    plots = []
    for result in select_rh_variants(results):
        parts = []
        for prefix in ("start", "end"):
            dates = pd.to_datetime(values["date"], errors="coerce")
            part = values.loc[(values["period"] == result["period"])
                & (dates >= result[f"{prefix}_window_begin"])
                & (dates <= result[f"{prefix}_window_end"])].copy()
            part = part.sort_values("date", kind="stable")
            if part.empty:
                break
            for key in ("power", "fuel"):
                part[key] = pd.to_numeric(part[key], errors="coerce")
                if not np.isfinite(part[key]).all():
                    raise ValueError(f"Период {result['period']}: недопустимые данные РХ в {prefix}.")
            parts.append(part)
        if len(parts) == 2:
            plots.append(RHPlot(result, *parts))
    return plots


def _bounds(values):
    low, high = float(np.min(values)), float(np.max(values))
    span = max(high - low, max(abs(low), abs(high)) * .01, .1)
    magnitude = 10 ** math.floor(math.log10(span / 6))
    step = next(unit * magnitude for unit in (1, 2, 5, 10) if unit * magnitude >= span / 6)
    return math.floor((low - .1 * span) / step) * step, math.ceil((high + .1 * span) / step) * step, step


def _series(sheet, x_column, y_column, first, last, x_values, y_values, title, color, line=False):
    series = Series(Reference(sheet, min_col=y_column, min_row=first, max_row=last),
                    Reference(sheet, min_col=x_column, min_row=first, max_row=last), title=title)
    for cache, values in ((series.xVal.numRef, x_values), (series.yVal.numRef, y_values)):
        cache.numCache = NumData(ptCount=len(values), pt=[NumVal(idx=i, v=float(v)) for i, v in enumerate(values)])
    if line:
        series.graphicalProperties.line.solidFill = color
        series.marker.symbol = "none"
        series.graphicalProperties.line.width = 19050
    else:
        series.graphicalProperties.line.noFill = True
        series.marker.symbol = "circle"
        series.marker.size = 3
        series.marker.graphicalProperties.solidFill = color
        series.marker.graphicalProperties.line.solidFill = color
    return series


def add_rh_charts(sheet, plots, start_row, *, two_columns=True):
    cells = {}
    bottom = start_row
    for index, plot in enumerate(plots):
        result = plot.result
        number = int(result["period"])
        data_sheet = sheet.parent.create_sheet(f"РХ П{number}")
        data_sheet.append([f"Период {number}: РХ, вариант {result['rank']}"])
        data_sheet.append(["Состояние", "Дата", "Nприв, МВт", "Bприв, нм³/ч", "Строка исходного Excel",
                           None, "N линии", "Bчист", "Bзагр"])
        combined = pd.concat([plot.start, plot.end], ignore_index=True)
        x = np.linspace(combined.power.min(), combined.power.max(), 100)
        clean = result["k_start"] * x + result["b_start"]
        dirty = result["k_end"] * x + result["b_end"]
        for i in range(max(len(combined), len(x))):
            row = [None] * 9
            if i < len(combined):
                point = combined.iloc[i]
                row[:5] = ["Условно-чистое" if i < len(plot.start) else "Условно-загрязнённое",
                    pd.Timestamp(point["date"]).to_pydatetime(), float(point.power), float(point.fuel),
                    int(point.excel_row) if "excel_row" in point and pd.notna(point.excel_row) else None]
            if i < len(x):
                row[6:] = [float(x[i]), float(clean[i]), float(dirty[i])]
            data_sheet.append(row)
        data_sheet.freeze_panes = "A3"
        for column in ("A", "B", "C", "D", "E", "G", "H", "I"):
            data_sheet.column_dimensions[column].width = 25

        column = 1 + (index % 2) * 25 if two_columns else 1
        top = start_row + (index // 2 if two_columns else index) * 42
        cells.setdefault(top, {})[column] = (f"Период {number}: расходная характеристика, вариант {result['rank']}", "period")
        sheet.merged_cells.add(f"{get_column_letter(column)}{top}:{get_column_letter(column + 22)}{top}")
        sheet.row_dimensions[top].height = 24
        chart = ScatterChart()
        chart.width, chart.height = 42, 18
        chart.title = None
        chart.scatterStyle = "lineMarker"
        chart.graphical_properties = GraphicalProperties(solidFill="FFFFFF", ln=LineProperties(noFill=True))
        for axis, title in ((chart.x_axis, "Приведённая мощность, МВт"),
                            (chart.y_axis, "Приведённый расход газа в КС ГТУ, нм³/ч")):
            axis.title = title
            axis.title.tx.rich = rich_text(title, bold=True)
            axis.title.txPr = rich_text("", bold=True)
            axis.txPr = rich_text("")
            axis.delete = False
            axis.numFmt = "0.0"
            axis.majorGridlines = ChartLines(spPr=GraphicalProperties(ln=LineProperties(solidFill="808080", w=9525)))
            axis.minorGridlines = ChartLines(spPr=GraphicalProperties(ln=LineProperties(solidFill="C0C0C0", w=4762)))
        chart.x_axis.scaling.min, chart.x_axis.scaling.max, chart.x_axis.majorUnit = _bounds(x)
        chart.y_axis.scaling.min, chart.y_axis.scaling.max, chart.y_axis.majorUnit = _bounds(np.r_[combined.fuel, clean, dirty])
        chart.x_axis.minorUnit = chart.x_axis.majorUnit / 5
        chart.y_axis.minorUnit = chart.y_axis.majorUnit / 5
        chart.x_axis.tickLblPos = "low"
        chart.legend.position = "b"
        chart.legend.overlay = False
        chart.legend.txPr = rich_text("")
        chart.legend.layout = Layout(manualLayout=ManualLayout(xMode="edge", yMode="edge", x=.1, y=.94, w=.8, h=.05))
        chart.layout = Layout(manualLayout=ManualLayout(layoutTarget="inner", xMode="edge", yMode="edge",
                                                       x=.09, y=.04, w=.86, h=.79))
        for part, first, title, color in ((plot.start, 3, "Условно-чистая", "4472C4"),
                (plot.end, len(plot.start) + 3, "Условно-загрязнённая", "C00000")):
            chart.series.append(_series(data_sheet, 3, 4, first, first + len(part) - 1,
                                        part.power, part.fuel, title, color))
        chart.series.append(_series(data_sheet, 7, 8, 3, 102, x, clean, "Линия чистая", "4472C4", True))
        chart.series.append(_series(data_sheet, 7, 9, 3, 102, x, dirty, "Линия загрязнённая", "C00000", True))
        xlow, xhigh = chart.x_axis.scaling.min, chart.x_axis.scaling.max
        ylow, yhigh = chart.y_axis.scaling.min, chart.y_axis.scaling.max
        for prefix, name, state, xr, yr, color in (
            ("end", "Bзагр", "Условно-загрязнённое", .38, .82, "C00000"),
            ("start", "Bчист", "Условно-чистое", .68, .25, "4472C4"),
        ):
            text = (f"{state} состояние {result[f'{prefix}_window_begin']:%d.%m.%Y}\n"
                    f"{rh_equation(name, result[f'k_{prefix}'], result[f'b_{prefix}'])}")
            chart.series.append(label_series(xlow + (xhigh - xlow) * xr,
                ylow + (yhigh - ylow) * yr, text, bold=True, color=color))
        chart.legend.legendEntry = [LegendEntry(idx=i, delete=True) for i in range(2, len(chart.series))]
        sheet.add_chart(chart, f"{get_column_letter(column)}{top + 2}")
        bottom = max(bottom, top + 39)
    return cells, bottom
