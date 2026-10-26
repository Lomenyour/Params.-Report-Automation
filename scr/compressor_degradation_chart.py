"""Графики КПД компрессора и степени сжатия по первой паре TOP-10 ВНА."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

import numpy as np
import pandas as pd
from openpyxl.cell import WriteOnlyCell
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines, NumericAxis
from openpyxl.chart.data_source import AxDataSource, NumData, NumDataSource, NumVal
from openpyxl.chart.label import DataLabel, DataLabelList
from openpyxl.chart.legend import LegendEntry
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.series import SeriesLabel, XYSeries
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText, Text
from openpyxl.chart.trendline import Trendline
from openpyxl.drawing.line import LineEndProperties, LineProperties
from openpyxl.drawing.text import (
    CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties,
    RegularTextRun, RichTextProperties,
)
from openpyxl.utils.datetime import to_excel
from openpyxl.styles import Alignment, Font, PatternFill

DATA_COLUMNS = (
    ("date", "Дата"), ("vna", "ВНА, %"), ("t", "tнк, °C"),
    ("p", "Pнк, мбар"), ("eta", "КПД компрессора, %"), ("pi_k", "πк"),
    ("excel_row", "Строка исходного Excel"),
)
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
    data_first: int = 6


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
        eta_lower, eta_upper = sorted((float(top["eta_1"]), float(top["eta_2"])))
        selected = selected.loc[
            selected["date"].notna() & np.isfinite(selected["eta"]) &
            np.isfinite(selected["pi_k"]) &
            selected["eta"].round(3).between(eta_lower, eta_upper)
        ].sort_values("date", kind="stable")
        if selected.empty:
            continue
        plots.append(CompressorPlot(
            number, selected[[key for key, _ in DATA_COLUMNS if key in selected]].reset_index(drop=True),
            top, lower, upper, t_lower, t_upper, p_lower, p_upper,
        ))
    return plots


def _criteria(plot, *, multiline=False):
    eta_lower, eta_upper = sorted((float(plot.top["eta_1"]), float(plot.top["eta_2"])))
    parts = [
        f"{plot.vna_lower:.1f} ≤ ВНА < {plot.vna_upper:.1f} %",
        f"{plot.t_lower:.3f} ≤ tнк ≤ {plot.t_upper:.3f} °C",
        f"{plot.p_lower:.3f} ≤ Pнк ≤ {plot.p_upper:.3f} мбар",
        f"{eta_lower:.3f} ≤ ηoi ≤ {eta_upper:.3f} %",
    ]
    return ("\n" if multiline else "; ").join(parts)


def _chart_number(value):
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _chart_criteria(plot):
    number = _chart_number
    return (
        f"{number(plot.vna_lower)} % ≤ ВНА ≤ {number(plot.vna_upper)} % = const.\n"
        f"{number(plot.t_lower)} °С ≤ tнк ≤ {number(plot.t_upper)} °С\n"
        f"{number(plot.p_lower)} мбар ≤ Pнк ≤ {number(plot.p_upper)} мбар"
    )


def _write_data_sheets(book, plots):
    sheets = {}
    for plot in plots:
        sheet = book.create_sheet(f"Компрессор П{plot.period}")
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A6"
        for index, width in enumerate((23, 14, 17, 20, 26, 16, 24), start=1):
            sheet.column_dimensions[_letter(index)].width = width
        sheet.row_dimensions[1].height = 26
        sheet.row_dimensions[2].height = 45
        sheet.merged_cells.add("A1:G1")
        sheet.merged_cells.add("A2:G2")
        def cell(value, *, header=False):
            if value is None or pd.isna(value):
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
        sheet.append([cell(f"Период {plot.period}. Данные деградации компрессора")])
        sheet.append([cell(_criteria(plot))])
        sheet.append([cell("Сопоставление границ — на точности TOP-10 (3 знака); значения ниже без округления.")])
        sheet.append([])
        sheet.append([cell(title, header=True) for _, title in DATA_COLUMNS])
        plot.data_first = 6
        for record in plot.points.to_dict("records"):
            cells = []
            for key, _ in DATA_COLUMNS:
                item = cell(record.get(key))
                item.number_format = "dd.mm.yyyy hh:mm" if key == "date" else (
                    "0" if key == "excel_row" else "0.000"
                )
                cells.append(item)
            sheet.append(cells)
        sheet.auto_filter.ref = f"A5:G{plot.data_first + len(plot.points) - 1}"
        sheets[plot.period] = sheet
    return sheets


def _series(sheet, plot, key, title, color, *, trend=False):
    first = plot.data_first
    last = first + len(plot.points) - 1
    column = [name for name, _ in DATA_COLUMNS].index(key) + 1
    series = Series(
        Reference(sheet, min_col=column, min_row=first, max_row=last),
        Reference(sheet, min_col=1, min_row=first, max_row=last),
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
            enumerate(plot.points[key])],
    )
    series.graphicalProperties.line.noFill = True
    series.marker.symbol = "circle"
    series.marker.size = 3
    series.marker.graphicalProperties.solidFill = color
    series.marker.graphicalProperties.line.solidFill = color
    if trend and len(plot.points) > 1:
        metric = "КПД" if key == "eta" else "Степень сжатия"
        series.trendline = Trendline(
            trendlineType="linear", name=f"Линейная ({metric})",
            dispEq=False, dispRSqr=False,
        )
        series.trendline.spPr = series.graphicalProperties.__class__()
        series.trendline.spPr.ln.solidFill = color
        series.trendline.spPr.ln.width = 25400
    return series


def _text(size=1400, *, bold=False, centered=False):
    return RichText(
        bodyPr=RichTextProperties(),
        p=[Paragraph(pPr=ParagraphProperties(algn="ctr" if centered else None, defRPr=CharacterProperties(
            sz=size, b=bold, solidFill="000000",
            latin=DrawingFont(typeface="Times New Roman"),
        )), endParaRPr=CharacterProperties(lang="ru-RU"))],
    )


def _rich_text(text, *, size=1600, bold=True, centered=True):
    def properties(*, subscript=False):
        return CharacterProperties(
            sz=round(size * 0.75) if subscript else size,
            b=bold, solidFill="000000", baseline=-25000 if subscript else 0,
            latin=DrawingFont(typeface="Times New Roman"),
        )

    paragraphs = []
    for line in text.split("\n"):
        runs = []
        position = 0
        for match in re.finditer(r"tнк|Pнк|ηoi|πк", line):
            runs.append(RegularTextRun(rPr=properties(), t=line[position:match.start()] + match[0][0]))
            runs.append(RegularTextRun(rPr=properties(subscript=True), t=match[0][1:]))
            position = match.end()
        if position < len(line) or not runs:
            runs.append(RegularTextRun(rPr=properties(), t=line[position:]))
        paragraphs.append(Paragraph(
            pPr=ParagraphProperties(algn="ctr" if centered else None, defRPr=properties()),
            r=runs, endParaRPr=properties(),
        ))
    return RichText(bodyPr=RichTextProperties(wrap="none", spcFirstLastPara=False), p=paragraphs)


class _RichDataLabel(DataLabel):
    """openpyxl 3.1 не описывает c:tx; добавляем штатный rich text Excel."""
    def __init__(self, text):
        super().__init__(idx=0, dLblPos="ctr", showSerName=False, showVal=False, showCatName=False)
        self.text = text

    def to_tree(self, tagname=None, idx=None, namespace=None):
        element = DataLabel(
            idx=self.idx, dLblPos="ctr", showSerName=False, showVal=False, showCatName=False,
        ).to_tree(tagname, idx, namespace)
        element.insert(1, Layout(manualLayout=ManualLayout(
            wMode="factor", hMode="factor", w=0.34 if "= const." in self.text else 0.16,
            h=0.15,
        )).to_tree("layout"))
        element.insert(2, Text(rich=_rich_text(self.text)).to_tree("tx"))
        return element


def _format_axis(axis, title):
    axis.delete = False
    axis.title = title
    axis.title.tx.rich = _rich_text(title, size=1400, centered=False)
    axis.title.txPr = _text(bold=True)
    axis.txPr = _text()
    axis.tickLblPos = "nextTo"
    axis.spPr = GraphicalProperties(
        ln=LineProperties(solidFill="808080", w=9525),
    )


def _value_scale(axis, values, *, upper=False):
    """Читаемая шкала по всем точкам, включая постоянные ряды."""
    low, high = float(values.min()), float(values.max())
    span = max(high - low, 1.0)
    lower = low - span * (3 if upper else 1)
    higher = high + span * (1 if upper else 3)
    raw_step = (higher - lower) / 6
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(unit * magnitude for unit in (1, 2, 5, 10)
                if unit * magnitude >= raw_step)
    axis.scaling.min = math.floor(lower / step) * step
    axis.scaling.max = math.ceil(higher / step) * step
    axis.majorUnit = step
    axis.minorUnit = step / 5
    axis.numFmt = "0.0" if step >= 0.1 else "0.00"


def _annotation(points, text, *, label=False):
    series = XYSeries(
        tx=SeriesLabel(v=text),
        xVal=AxDataSource(numLit=NumData(ptCount=len(points), pt=[
            NumVal(idx=index, v=to_excel(pd.Timestamp(date).to_pydatetime()))
            for index, (date, _) in enumerate(points)
        ])),
        yVal=NumDataSource(numLit=NumData(ptCount=len(points), pt=[
            NumVal(idx=index, v=float(value))
            for index, (_, value) in enumerate(points)
        ])),
    )
    series.marker.symbol = "none"
    if label:
        series.graphicalProperties.line.noFill = True
        series.dLbls = DataLabelList(
            dLbl=[_RichDataLabel(text)],
            showSerName=False, showVal=False, showCatName=False,
            showLegendKey=False, dLblPos="ctr", txPr=_text(1600, bold=True, centered=True),
            spPr=GraphicalProperties(
                solidFill="FFFFFF", ln=LineProperties(solidFill="000000", w=12700),
            ),
        )
        series.dLbls.txPr.bodyPr.wrap = "none"
        series.dLbls.txPr.bodyPr.spAutoFit = True
    else:
        series.graphicalProperties.line.solidFill = "000000"
        series.graphicalProperties.line.width = 12700
        series.graphicalProperties.line.headEnd = LineEndProperties(type="triangle", w="sm", len="sm")
        series.graphicalProperties.line.tailEnd = LineEndProperties(type="triangle", w="sm", len="sm")
    return series


def _add_annotations(chart, secondary, plot):
    low, high = chart.y_axis.scaling.min, chart.y_axis.scaling.max
    other_low, other_high = secondary.y_axis.scaling.min, secondary.y_axis.scaling.max
    for suffix in ("1", "2"):
        moment = pd.Timestamp(plot.top[f"date_{suffix}"])
        eta = float(plot.top[f"eta_{suffix}"])
        pi_k = float(plot.top[f"pi_k_{suffix}"])
        pi_y = low + (pi_k - other_low) / (other_high - other_low) * (high - low)
        chart.series.append(_annotation([(moment, pi_y), (moment, eta)], "Граница TOP-1"))
        eta_text = f"{eta:.2f}".replace(".", ",")
        pi_text = f"{pi_k:.3f}".replace(".", ",")
        text = f"{moment:%d.%m.%Y}\nηoi = {eta_text} %\nπк = {pi_text}"
        chart.series.append(_annotation([(moment, low + (high - low) * 0.48)], text, label=True))
    middle = pd.Timestamp(plot.top["date_1"]) + (
        pd.Timestamp(plot.top["date_2"]) - pd.Timestamp(plot.top["date_1"])
    ) / 2
    chart.series.append(_annotation(
        [(middle, low + (high - low) * 0.90)], _chart_criteria(plot), label=True,
    ))
    chart.legend.legendEntry = [LegendEntry(idx=index, delete=True)
                                for index in range(1, len(chart.series))]


def add_compressor_charts(sheet, plots, start_row, *, two_columns=True):
    """Добавляет редактируемые Excel-графики и подписи в видимые ячейки."""
    cells = {}
    data_sheets = _write_data_sheets(sheet.parent, plots)
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
        criteria = _criteria(plot)
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
        _value_scale(chart.y_axis, plot.points["eta"], upper=True)
        chart.y_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="000000", w=12700)
        ))
        chart.y_axis.minorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="A6A6A6", w=6350)
        ))
        chart.x_axis.majorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="000000", w=12700)
        ))
        chart.x_axis.minorGridlines = ChartLines(spPr=GraphicalProperties(
            ln=LineProperties(solidFill="A6A6A6", w=6350)
        ))
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
            data_sheets[plot.period], plot, "eta", "КПД", "00B050", trend=True
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
            data_sheets[plot.period], plot, "pi_k", "Степень сжатия", "7030A0", trend=True
        ))
        _add_annotations(chart, secondary, plot)
        chart += secondary
        first_trend = sum(len(part.series) for part in chart._charts)
        trend_count = sum(series.trendline is not None
                          for part in chart._charts for series in part.series)
        chart.legend.legendEntry.extend(
            LegendEntry(idx=first_trend + index, delete=True)
            for index in range(trend_count)
        )
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
