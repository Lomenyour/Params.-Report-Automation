"""GUI rendering of the same CompressorPlot objects used by Excel."""
from __future__ import annotations

import io

import matplotlib.dates as mdates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, MultipleLocator
import numpy as np
import pandas as pd
from openpyxl.chart.axis import NumericAxis
from openpyxl.utils.datetime import from_excel

from compressor_degradation_chart import _chart_criteria, _date_scale, _value_scale


def compressor_preview_figure(plot):
    """Render existing points/criteria; no analytical results are recalculated."""
    figure = Figure(figsize=(14, 8.8), dpi=100, facecolor='white')
    axis = figure.add_subplot(111)
    other = axis.twinx()
    figure.subplots_adjust(left=.10, right=.89, top=.88, bottom=.21)
    x = mdates.date2num(plot.points['date'].to_numpy())
    handles = []
    for target, key, color, label, upper in (
            (axis, 'eta', '#00B050', 'КПД', True),
            (other, 'pi_k', '#7030A0', 'Степень сжатия', False)):
        y = plot.points[key].to_numpy(dtype=float)
        points, = target.plot(x, y, 'o', color=color, markersize=3, label=label)
        handles.append(points)
        if len(x) > 1 and np.ptp(x) > 0:
            # Linear Excel trendline, using a local date origin for stability.
            coefficients = np.polyfit(x - x[0], y, 1)
            target.plot(x, np.polyval(coefficients, x - x[0]), color=color, linewidth=1.5)
        scale = NumericAxis()
        _value_scale(scale, plot.points[key], upper=upper)
        target.set_ylim(scale.scaling.min, scale.scaling.max)
        target.yaxis.set_major_locator(MultipleLocator(scale.majorUnit))
        target.yaxis.set_minor_locator(MultipleLocator(scale.minorUnit))
        target.tick_params(axis='both', labelsize=16)
    dates = NumericAxis()
    _date_scale(dates, plot.points['date'])
    convert = lambda value: mdates.date2num(from_excel(float(value)))
    axis.set_xlim(convert(dates.scaling.min), convert(dates.scaling.max))
    ticks = np.arange(dates.scaling.min, dates.scaling.max + dates.majorUnit * .01, dates.majorUnit)
    axis.xaxis.set_major_locator(FixedLocator([convert(value) for value in ticks]))
    axis.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
    axis.xaxis.set_minor_locator(MultipleLocator(dates.minorUnit))
    axis.tick_params(axis='x', labelrotation=30)
    axis.grid(which='major', color='#555555', linewidth=.7)
    axis.grid(which='minor', color='#A6A6A6', linewidth=.4)
    axis.set_xlabel('Дата', fontsize=16)
    axis.set_ylabel('Внутренний относительный КПД ОК, %', fontsize=16)
    other.set_ylabel('Степень повышения давления, о.е.', fontsize=16)
    figure.suptitle(f'Период {plot.period}. Деградация компрессора — пара №{plot.pair_rank}', fontsize=16)
    low, high = axis.get_ylim()
    pi_low, pi_high = other.get_ylim()
    box = dict(boxstyle='square,pad=.4', facecolor='white', edgecolor='black', linewidth=.8)
    for suffix in ('1', '2'):
        date = pd.Timestamp(plot.top[f'date_{suffix}'])
        moment = mdates.date2num(date.to_datetime64())
        eta, pi = float(plot.top[f'eta_{suffix}']), float(plot.top[f'pi_k_{suffix}'])
        pi_y = low + (pi - pi_low) / (pi_high - pi_low) * (high - low)
        axis.annotate('', xy=(moment, eta), xytext=(moment, pi_y),
                      arrowprops=dict(arrowstyle='<->', color='black', linewidth=1))
        text = f'{date:%d.%m.%Y}\nηoi = {eta:.1f} %\nπк = {pi:.1f}'
        axis.text(moment, low + (high-low)*.48, text, ha='center', va='center',
                  fontsize=12, fontweight='bold', bbox=box)
    middle = (mdates.date2num(pd.Timestamp(plot.top['date_1']).to_datetime64()) +
              mdates.date2num(pd.Timestamp(plot.top['date_2']).to_datetime64())) / 2
    axis.text(middle, low + (high-low)*.90, _chart_criteria(plot), ha='center', va='center',
              fontsize=12, fontweight='bold', bbox=box)
    figure.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5, .015), ncol=2, fontsize=16)
    return figure


def render_compressor_preview(plot):
    figure = compressor_preview_figure(plot)
    try:
        output = io.BytesIO()
        FigureCanvasAgg(figure).print_png(output)
        return output.getvalue()
    finally:
        figure.clear()
