"""Графики КПД компрессора и степени сжатия по первой паре TOP-10 ВНА."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines, NumericAxis
from openpyxl.chart.data_source import NumData, NumVal
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.chart.trendline import Trendline
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import (
    CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties,
    RichTextProperties,
)
from openpyxl.utils.datetime import to_excel

HELPER_COLUMN = 67  # BO:BQ, за существующими скрытыми данными диаграмм.
HELPER_HEADERS = ("Дата", "КПД компрессора, %", "πк")
CHART_ROWS = 49


@dataclass
class CompressorPlot:
    period: int
    points: pd.DataFrame
    top: pd.Series
    vna_lower: float
    vna_upper: float
    t_lower: float
    t_upper: float
    p_lower: float
    p_upper: float
    helper_first: int = 0


def prepare_compressor_plots(values, periods, top10_results):
    """Берёт TOP-1 каждого периода и фильтрует только строки этого периода."""
    if values is None or values.empty or periods is None or periods.empty:
        return []
    by_period = {
        int(table.attrs["period_number"]): table.iloc[0]
        for table in (top10_results or [])
        if table is not None and not table.empty and "period_number" in table.attrs
    }
    plots = []
    dates = pd.to_datetime(values["date"], errors="coerce")
    for period in periods.itertuples(index=False):
        number = int(period.period)
        top = by_period.get(number)
        if top is None:
            continue
        lower, upper = (float(bound.replace(",", "."))
                        for bound in str(top["vna_interval"]).split("-", 1))
        t_lower, t_upper = sorted((float(top["t_1"]), float(top["t_2"])))
        p_lower, p_upper = sorted((float(top["p_1"]), float(top["p_2"])))
        vna = pd.to_numeric(values["vna"], errors="coerce")
        temperature = pd.to_numeric(values["t"], errors="coerce").round(3)
        pressure = pd.to_numeric(values["p"], errors="coerce").round(3)
        # Граница интервала ВНА справа открыта, как в поиске TOP-10.
        in_period = (values["period"] == number) if "period" in values else (
            (dates >= pd.Timestamp(period.date_start)) &
            (dates <= pd.Timestamp(period.date_end))
        )
        selected = values.loc[
            in_period & vna.ge(lower) & vna.lt(upper) &
            temperature.between(t_lower, t_upper) &
            pressure.between(p_lower, p_upper)
        ].copy()
        if selected.empty:
            continue
        selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
        selected["pi_k"] = pd.to_numeric(selected["pi_k"], errors="coerce")
        selected["eta"] = pd.to_numeric(selected["eta_compressor"], errors="coerce")
        selected = selected.loc[
            selected["date"].notna() & np.isfinite(selected["eta"]) &
            np.isfinite(selected["pi_k"])
        ].sort_values("date", kind="stable")
        if selected.empty:
            continue
        plots.append(CompressorPlot(
            number, selected[["date", "eta", "pi_k"]].reset_index(drop=True),
            top, lower, upper, t_lower, t_upper, p_lower, p_upper,
        ))
    return plots


def _series(sheet, plot, column, title, color, *, trend=False):
    first = plot.helper_first
    last = first + len(plot.points) - 1
    series = Series(
        Reference(sheet, min_col=column, min_row=first, max_row=last),
        Reference(sheet, min_col=HELPER_COLUMN, min_row=first, max_row=last),
        title=title,
    )
    series.xVal.numRef.numCache = NumData(
        formatCode="dd.mm.yyyy", ptCount=len(plot.points),
        pt=[NumVal(idx=i, v=to_excel(date.to_pydatetime()))
            for i, date in enumerate(plot.points["date"])],
    )
    series.yVal.numRef.numCache = NumData(
        ptCount=len(plot.points),
        pt=[NumVal(idx=i, v=float(value)) for i, value in
            enumerate(plot.points["eta" if column == HELPER_COLUMN + 1 else "pi_k"])],
    )
    series.graphicalProperties.line.noFill = True
    series.marker.symbol = "circle"
    series.marker.size = 3
    series.marker.graphicalProperties.solidFill = color
    series.marker.graphicalProperties.line.solidFill = color
    if trend and len(plot.points) > 1:
        metric = "КПД" if column == HELPER_COLUMN + 1 else "Степень сжатия"
        series.trendline = Trendline(
            trendlineType="linear", name=f"Линейная ({metric})",
            dispEq=False, dispRSqr=False,
        )
        series.trendline.spPr = series.graphicalProperties.__class__()
        series.trendline.spPr.ln.solidFill = color
        series.trendline.spPr.ln.width = 25400
    return series


def _text(size=1100, *, bold=False):
    return RichText(
        bodyPr=RichTextProperties(),
        p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(
            sz=size, b=bold, solidFill="000000",
            latin=DrawingFont(typeface="Times New Roman"),
        )), endParaRPr=CharacterProperties(lang="ru-RU"))],
    )


def _format_axis(axis, title):
    axis.delete = False
    axis.title = title
    axis.title.txPr = _text(bold=True)
    axis.txPr = _text()
    axis.tickLblPos = "nextTo"
    axis.spPr = GraphicalProperties(
        ln=LineProperties(solidFill="808080", w=9525),
    )


def _value_scale(axis, values):
    """Читаемая шкала по всем точкам, включая постоянные ряды."""
    low, high = float(values.min()), float(values.max())
    span = max(high - low, 1.0)
    middle = (low + high) / 2
    raw_step = span / 6
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(unit * magnitude for unit in (1, 2, 5, 10)
                if unit * magnitude >= raw_step)
    axis.scaling.min = math.floor((middle - span * 0.6) / step) * step
    axis.scaling.max = math.ceil((middle + span * 0.6) / step) * step
    axis.majorUnit = step
    axis.minorUnit = step / 5
    axis.numFmt = "0.0" if step >= 0.1 else "0.00"


def add_compressor_charts(sheet, plots, start_row, *, two_columns=True):
    """Добавляет редактируемые Excel-графики и подписи в видимые ячейки."""
    cells = {}
    for index, plot in enumerate(plots):
        column = 1 + (index % 2) * 25 if two_columns else 1
        block_row = start_row + (index // 2 if two_columns else index) * CHART_ROWS
        top = plot.top
        sheet.merged_cells.add(
            f"{_letter(column)}{block_row}:{_letter(column + 22)}{block_row}"
        )
        cells.setdefault(block_row, {})[column] = (
            f"Период {plot.period}. Деградация компрессора — TOP-1 ВНА", "period"
        )
        sheet.row_dimensions[block_row].height = 25
        criteria = (
            f"{plot.vna_lower:.1f} ≤ ВНА < {plot.vna_upper:.1f} %; "
            f"{plot.t_lower:.3f} ≤ tнк ≤ {plot.t_upper:.3f} °C; "
            f"{plot.p_lower:.3f} ≤ Pнк ≤ {plot.p_upper:.3f} мбар"
        )
        sheet.merged_cells.add(
            f"{_letter(column)}{block_row + 1}:{_letter(column + 22)}{block_row + 1}"
        )
        cells.setdefault(block_row + 1, {})[column] = (criteria, "body")
        sheet.row_dimensions[block_row + 1].height = 24

        chart = ScatterChart()
        chart.roundedCorners = False
        chart.graphical_properties = GraphicalProperties(
            solidFill="FFFFFF", ln=LineProperties(noFill=True),
        )
        chart.plot_area.spPr = GraphicalProperties(
            solidFill="FFFFFF", ln=LineProperties(solidFill="808080", w=9525),
        )
        chart.scatterStyle = "marker"
        chart.width = 42 if two_columns else 36
        chart.height = 18
        chart.x_axis.axId = 200 + index * 4
        chart.y_axis.axId = 201 + index * 4
        chart.x_axis.crossAx = chart.y_axis.axId
        chart.y_axis.crossAx = chart.x_axis.axId
        _format_axis(chart.x_axis, "Дата")
        chart.x_axis.numFmt = "dd.mm.yyyy"
        chart.x_axis.axPos = "b"
        chart.x_axis.tickLblPos = "low"
        _format_axis(chart.y_axis, "КПД компрессора, %")
        chart.y_axis.axPos = "l"
        chart.y_axis.crosses = "min"
        _value_scale(chart.y_axis, plot.points["eta"])
        chart.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="A6A6A6", w=9525)
        ))
        chart.y_axis.minorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="D9D9D9", w=4762)
        ))
        chart.x_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="A6A6A6", w=9525)
        ))
        chart.x_axis.minorGridlines = None
        chart.legend.position = "b"
        chart.legend.overlay = False
        chart.legend.txPr = _text()
        chart.legend.layout = Layout(manualLayout=ManualLayout(
            xMode="edge", yMode="edge", x=0.1, y=0.94, w=0.8, h=0.05,
        ))
        chart.layout = Layout(manualLayout=ManualLayout(
            layoutTarget="inner", xMode="edge", yMode="edge",
            x=0.09, y=0.04, w=0.81, h=0.80,
        ))
        chart.visible_cells_only = False
        chart.display_blanks = "gap"
        first_date, last_date = plot.points["date"].iloc[[0, -1]]
        chart.x_axis.scaling.min = to_excel(
            (first_date.normalize() - pd.DateOffset(months=2)).to_pydatetime()
        )
        chart.x_axis.scaling.max = to_excel(
            (last_date.normalize() + pd.DateOffset(months=2)).to_pydatetime()
        )
        span_days = chart.x_axis.scaling.max - chart.x_axis.scaling.min
        chart.x_axis.majorUnit = next(
            (days for days in (1, 2, 5, 10, 20, 25, 50, 100, 150, 200, 365)
             if days >= span_days / 6), 365,
        )
        chart.x_axis.minorUnit = chart.x_axis.majorUnit / 5
        chart.series.append(_series(
            sheet, plot, HELPER_COLUMN + 1, "КПД компрессора, %", "00B050", trend=True
        ))

        secondary = ScatterChart()
        secondary.scatterStyle = "marker"
        secondary.x_axis = NumericAxis(
            axId=203 + index * 4, crossAx=202 + index * 4,
            axPos="b", delete=True,
        )
        secondary.x_axis.majorGridlines = None
        secondary.x_axis.minorGridlines = None
        secondary.y_axis.axId = 202 + index * 4
        secondary.y_axis.crossAx = secondary.x_axis.axId
        secondary.y_axis.axPos = "r"
        secondary.y_axis.crosses = "max"
        _format_axis(secondary.y_axis, "Степень сжатия πк")
        _value_scale(secondary.y_axis, plot.points["pi_k"])
        secondary.y_axis.majorGridlines = None
        secondary.y_axis.minorGridlines = None
        secondary.x_axis.scaling.min = chart.x_axis.scaling.min
        secondary.x_axis.scaling.max = chart.x_axis.scaling.max
        secondary.series.append(_series(
            sheet, plot, HELPER_COLUMN + 2, "Степень сжатия πк", "7030A0", trend=True
        ))
        chart += secondary
        sheet.add_chart(chart, f"{_letter(column)}{block_row + 3}")

        for offset, side, suffix in ((0, "Начальная точка", "1"),
                                     (12, "Конечная точка", "2")):
            row = block_row + 43
            target = column + offset
            sheet.merged_cells.add(
                f"{_letter(target)}{row}:{_letter(target + 10)}{row}"
            )
            date = pd.Timestamp(top[f"date_{suffix}"])
            text = (
                f"{side}: {date:%d.%m.%Y %H:%M}; "
                f"ηoi = {float(top[f'eta_{suffix}']):.2f} %; "
                f"πк = {float(top[f'pi_k_{suffix}']):.3f}"
            )
            cells.setdefault(row, {})[target] = (text, "body")
            sheet.row_dimensions[row].height = 25
    if not plots:
        return cells, start_row
    rows = (len(plots) + 1) // 2 if two_columns else len(plots)
    return cells, start_row + rows * CHART_ROWS - 1


def _letter(column):
    from openpyxl.utils import get_column_letter
    return get_column_letter(column)
