"""Выбор из существующих трёх вариантов и нативная РХ с верными датами."""
import copy
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from RH_raschet import select_rh_variants, plot_selected_windows
from rh_chart import prepare_rh_plots, add_rh_charts
from rh_display import power_bounds, dirty_above_clean, parallel_state_arrows


class RHSingleChartTest(unittest.TestCase):
    def candidate(self, rank, end_slope, period=1, end_b=6600.):
        first = pd.Timestamp(2026, period, 1)
        return {"period": period, "rank": rank, "k_start": 200., "k_end": end_slope,
                "b_start": 6500., "b_end": end_b,
                "start_window_begin": first, "start_window_end": first + pd.Timedelta(hours=23.5),
                "end_window_begin": first + pd.Timedelta(days=2),
                "end_window_end": first + pd.Timedelta(days=2, hours=23.5)}

    def values(self):
        result = []
        for start, k, b in (("2026-01-01", 200., 6500.), ("2026-01-03", 201., 6600.)):
            for index, date in enumerate(pd.date_range(start, periods=48, freq="30min")):
                power = 65. + index * .4
                result.append({"date": date, "period": 1, "power": power,
                               "fuel": k * power + b, "excel_row": len(result) + 2})
        return pd.DataFrame(result)

    def test_selection_first_second_third_equal_fallback_and_short_lists(self):
        for intercepts, rank in (([6600., 6700., 6800.], 1), ([6400., 6600., 6700.], 2),
                             ([6400., 6300., 6600.], 3), ([6400., 6300., 6200.], 1),
                             ([6500.], 1), ([6500., 6600.], 2), ([6500., 6500., 6600.], 3)):
            with self.subTest(intercepts=intercepts):
                rows = [self.candidate(i + 1, 200., end_b=b) for i, b in enumerate(intercepts)]
                original = copy.deepcopy(rows)
                self.assertEqual(select_rh_variants(rows, self.values())[0]["rank"], rank)
                self.assertEqual(rows, original)
        self.assertEqual(select_rh_variants([]), [])

    def test_each_period_selected_independently_by_signed_b(self):
        rows = [self.candidate(1, 200., end_b=6400.), self.candidate(2, 199., end_b=6800.),
                self.candidate(1, 200., 2), self.candidate(2, 200., 2)]
        second = self.values()
        second['period'] = 2
        second['date'] += pd.DateOffset(months=1)
        selected = select_rh_variants(rows, pd.concat([self.values(), second]))
        self.assertEqual([(row["period"], row["rank"]) for row in selected], [(1, 2), (2, 1)])
        self.assertLess(selected[0]['k_end'], selected[0]['k_start'])
        negative = [self.candidate(1, 200., end_b=-3500.), self.candidate(2, 200., end_b=-3300.)]
        for row in negative:
            row['b_start'] = -3400.
        self.assertEqual(select_rh_variants(negative, self.values())[0]['rank'], 2)

    def test_five_percent_slope_tolerance_does_not_prevent_crossing(self):
        rows = [self.candidate(1, 198., end_b=6650.), self.candidate(2, 199., end_b=6800.)]
        bounds = power_bounds(self.values(), rows[0])
        self.assertLess(abs(rows[0]['k_end']/rows[0]['k_start'] - 1), .05)
        self.assertLess(abs(rows[0]['b_end']/rows[0]['b_start'] - 1), .05)
        self.assertTrue(bounds[0] < 75 < bounds[1])
        self.assertFalse(dirty_above_clean(rows[0], bounds))
        self.assertTrue(dirty_above_clean(rows[1], bounds))
        self.assertEqual(select_rh_variants(rows, self.values())[0]['rank'], 2)
        self.assertIs(select_rh_variants(rows[:1], self.values())[0], rows[0])
        rows[0]['k_end'] = float('nan')
        self.assertEqual(select_rh_variants(rows, self.values())[0]['rank'], 2)

    def test_manual_axis_fallback_keeps_both_arrows_at_degenerate_direction(self):
        result = dict(k_start=-38., k_end=-40., b_start=10., b_end=11.)
        arrows = parallel_state_arrows(result, (0.,1.), (0.,1.),
            {'end':(.3,.8), 'start':(.7,.3)}, (0.,1.))
        self.assertEqual(set(arrows), {'end','start'})
        for prefix, (_, target) in arrows.items():
            self.assertTrue(np.isfinite(target).all())
            self.assertAlmostEqual(target[1],result[f'k_{prefix}']*target[0]+result[f'b_{prefix}'])

    def test_excel_and_gui_use_same_candidate_and_preserve_window_values(self):
        rows = [self.candidate(1, 200., end_b=6400.), self.candidate(2, 201.), self.candidate(3, 202.)]
        values = self.values()
        original = values.copy(deep=True)
        plots = prepare_rh_plots(values, rows)
        self.assertEqual(len(plots), 1)
        self.assertEqual(plots[0].result["rank"], 2)
        figure = plot_selected_windows(values, rows, show=False)
        self.addCleanup(plt.close, figure)
        self.assertEqual(len([axis for axis in figure.axes if axis.has_data()]), 1)
        self.assertIn("вариант №2", figure.axes[0].get_title())
        self.assertEqual(figure.axes[0].xaxis.label.get_size(), 16)
        axis = figure.axes[0]
        texts = [text for text in axis.texts if text.get_bbox_patch() is not None]
        arrows_gui = [text for text in axis.texts if getattr(text, 'arrow_patch', None) is not None]
        self.assertEqual(len(arrows_gui), 2)
        vectors = []
        for box, arrow, prefix in zip(texts, arrows_gui, ('end', 'start')):
            rect = box.get_bbox_patch().get_window_extent(figure.canvas.get_renderer())
            expected = ((rect.x0 + rect.x1) / 2, rect.y0 if prefix == 'end' else rect.y1)
            actual = axis.transData.transform(arrow.get_position())
            np.testing.assert_allclose(actual, expected, atol=1e-6)
            end = axis.transData.transform(arrow.xy)
            vectors.append(end - actual)
            self.assertAlmostEqual(arrow.xy[1], plots[0].result[f'k_{prefix}']*arrow.xy[0]+plots[0].result[f'b_{prefix}'])
        self.assertAlmostEqual(vectors[0][0]*vectors[1][1] - vectors[0][1]*vectors[1][0], 0., places=6)
        book = Workbook(write_only=True)
        sheet = book.create_sheet("Графики")
        cells, bottom = add_rh_charts(sheet, plots, 1)
        for i in range(1, bottom + 1):
            sheet.append([cells[i][1][0]] if i in cells else [])
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        with ZipFile(output) as archive:
            ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
                  "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            chart = ET.fromstring(archive.read("xl/charts/chart1.xml"))
            # DrawingML разрешает только один способ заливки линии.
            # Excel отвергает сочетание noFill и solidFill, хотя XML читается.
            for line in chart.findall(".//a:ln", ns):
                fills = [line.find(f"a:{kind}", ns) for kind in
                         ("noFill", "solidFill", "gradFill", "pattFill")]
                self.assertLessEqual(sum(fill is not None for fill in fills), 1)
            labels = ["".join(label.itertext()) for label in chart.findall(".//c:dLbl/c:tx/c:rich", ns)]
            self.assertIn('"Условно-чистое"состояние 01.01.2026', labels[1])
            self.assertIn('"Условно-загрязнённое"состояние 03.01.2026', labels[0])
            for label in chart.findall(".//c:dLbl", ns):
                self.assertIsNotNone(label.find("c:layout/c:manualLayout/c:w", ns))
                self.assertEqual(label.find("c:tx/c:rich/a:p/a:pPr/a:defRPr", ns).get("sz"), "1400")
                paragraphs = label.findall("c:tx/c:rich/a:p", ns)
                self.assertEqual(len(paragraphs), 3)
                text = ''.join(label.itertext())
                self.assertIn(' · N', text)
                self.assertNotIn('×', text)
            arrows = [series for series in chart.findall('.//c:ser', ns)
                      if series.find('c:spPr/a:ln/a:tailEnd', ns) is not None]
            self.assertEqual(len(arrows), 2)
            for arrow, prefix in zip(arrows, ('end', 'start')):
                x = float(arrow.findall('c:xVal/c:numLit/c:pt/c:v', ns)[-1].text)
                y = float(arrow.findall('c:yVal/c:numLit/c:pt/c:v', ns)[-1].text)
                self.assertAlmostEqual(y, plots[0].result[f'k_{prefix}']*x + plots[0].result[f'b_{prefix}'])
            axes = chart.findall('.//c:valAx', ns)
            scales = [(float(a.find('c:scaling/c:min', ns).get('val')),
                       float(a.find('c:scaling/c:max', ns).get('val'))) for a in axes]
            vectors = []
            labels = chart.findall('.//c:dLbl/c:layout/c:manualLayout', ns)
            for arrow, label, prefix in zip(arrows, labels, ('end', 'start')):
                xs = [float(v.text) for v in arrow.findall('c:xVal//c:pt/c:v', ns)]
                ys = [float(v.text) for v in arrow.findall('c:yVal//c:pt/c:v', ns)]
                rect = {key: float(label.find(f'c:{key}', ns).get('val')) for key in ('x','y','w','h')}
                xn = (rect['x'] + rect['w']/2 - .16)/.79
                yn = 1 - (rect['y'] + (rect['h'] if prefix == 'end' else 0) - .04)/.79
                self.assertAlmostEqual(xs[0], scales[0][0] + xn*(scales[0][1]-scales[0][0]))
                self.assertAlmostEqual(ys[0], scales[1][0] + yn*(scales[1][1]-scales[1][0]))
                vectors.append((xs[1]-xs[0],ys[1]-ys[0]))
                self.assertTrue(values.power.min() <= xs[1] <= values.power.max())
            cross = vectors[0][0]*vectors[1][1] - vectors[0][1]*vectors[1][0]
            self.assertAlmostEqual(cross, 0., places=6)
        output.seek(0)
        saved = load_workbook(output)
        data = saved["Данные РХ"]
        self.assertEqual(data["C3"].value, values.iloc[0].power)
        self.assertEqual(data["D3"].value, values.iloc[0].fuel)
        self.assertEqual(data["E3"].value, values.iloc[0].excel_row)
        self.assertEqual(len(saved["Графики"]._charts), 1)
        chart = saved["Графики"]._charts[0]
        self.assertEqual(chart.anchor.to.col - chart.anchor._from.col, 14)
        self.assertEqual(chart.anchor.to.row - chart.anchor._from.row, 33)
        self.assertEqual(chart.anchor.editAs, "twoCell")
        pd.testing.assert_frame_equal(values, original)

    def test_three_periods_share_sheet_without_crossing_data_or_curve_ranges(self):
        parts, candidates = [], []
        for number in (1, 2, 3):
            part = self.values()
            part["period"] = number
            part["date"] += pd.DateOffset(months=number - 1)
            part["fuel"] += number * 1000
            parts.append(part)
            candidates.append(self.candidate(1, 201., number))
        values = pd.concat(parts, ignore_index=True)
        original = values.copy(deep=True)
        book = Workbook(write_only=True)
        sheet = book.create_sheet("Графики")
        cells, bottom = add_rh_charts(sheet, prepare_rh_plots(values, candidates), 1)
        for _ in range(bottom):
            sheet.append([])
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        saved = load_workbook(output)
        self.assertEqual(saved.sheetnames, ["Графики", "Данные РХ"])
        source = saved["Данные РХ"]
        for number, chart in enumerate(saved["Графики"]._charts, 1):
            first = 3 + (number - 1) * 104
            self.assertIn(f"'Данные РХ'!$D${first}:$D${first+47}", chart.series[0].yVal.numRef.f)
            self.assertIn(f"'Данные РХ'!$D${first+48}:$D${first+95}", chart.series[1].yVal.numRef.f)
            self.assertIn(f"'Данные РХ'!$H${first}:$H${first+99}", chart.series[2].yVal.numRef.f)
            self.assertEqual(source[f"B{first}"].value, pd.Timestamp(2026, number, 1))
            self.assertEqual(source[f"D{first}"].value, parts[number-1].iloc[0].fuel)
            self.assertAlmostEqual(source[f"H{first}"].value,
                candidates[number-1]["k_start"] * source[f"G{first}"].value + candidates[number-1]["b_start"])
        pd.testing.assert_frame_equal(values, original)


if __name__ == "__main__":
    unittest.main()
