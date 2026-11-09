"""Проверка сводки деградации и выбора точек для диаграммы Excel."""

import io
import sys
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.utils.datetime import from_excel


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from degradation_chart import DATA_SHEET_NAME, prepare_degradation_plot, _delta_label  # noqa: E402
from pressure_chart import PressureChartData, write_pressure_sheet  # noqa: E402
from RH_raschet import build_weighted_delta_summary  # noqa: E402


class DegradationSummaryChartTest(unittest.TestCase):
    def test_weighted_summary_counts_only_power_loss_and_fuel_growth(self):
        table = pd.DataFrame({
            "Период": [1, 2, 3],
            "Часы начала": [0.0, 10.0, 30.0],
            "Часы конца": [10.0, 30.0, 60.0],
            "ΔNприв": [2.0, -4.0, -2.0],
            "Δbприв": [-2.0, 4.0, 1.0],
            "Δη, п.п.": [0.0, -0.1, -0.2],
        })
        table.attrs["period_start_values"] = {1: {"N": 100.0, "b": 200.0}}
        original = table.copy(deep=True)

        summary = build_weighted_delta_summary(table)

        self.assertAlmostEqual(summary["delta_n"], 140.0 / 60.0)
        self.assertAlmostEqual(summary["delta_b"], 110.0 / 60.0)
        self.assertAlmostEqual(summary["delta_n_percent"], 140.0 / 60.0)
        self.assertAlmostEqual(summary["delta_b_percent"], 110.0 / 60.0 / 2.0)
        pd.testing.assert_frame_equal(table, original)

    def test_chart_uses_each_periods_own_vna_interval(self):
        records = []
        for period, base, interval in (
            (1, "2026-01-01", 86),
            (2, "2026-02-01", 85),
            (3, "2026-03-01", 87),
        ):
            for index, offset in enumerate((0.2, 0.4, -0.7)):
                records.append({
                    "period": period,
                    "date": pd.Timestamp(base) + pd.Timedelta(minutes=30 * index),
                    "vna": interval + offset,
                    "power": 100 - period - index,
                    "fuel_specific": (
                        1700 if period == 1 and index == 0
                        else 280 + period + index
                    ),
                    "eta_gtu": 28 - period,
                    "vlo": 100 + index,
                    "fgo_fto": 200 + index,
                    "power_n": 80 + index,
                })
        values = pd.DataFrame(records)
        periods = pd.DataFrame([
            {
                "period": number,
                "date_start": group["date"].min(),
                "date_end": group["date"].max(),
            }
            for number, group in values.groupby("period")
        ])
        deltas = pd.DataFrame({
            "Период": [1, 2, 3],
            "ΔNприв": [2.0, -4.0, -3.0],
            "Δbприв": [-1.0, 2.0, 3.0],
            "Δη, п.п.": [0.0, -0.1, -0.2],
        })
        deltas.attrs["vna_intervals"] = {
            1: (86.0, 87.0, 2),
            2: (85.0, 86.0, 2),
            3: (87.0, 88.0, 2),
        }

        plot = prepare_degradation_plot(values, periods, deltas)
        self.assertEqual(len(plot.points), 6)
        self.assertEqual(
            [(p["period"], p["vna_start"], p["count"]) for p in plot.periods],
            [(1, 86.0, 2), (2, 85.0, 2), (3, 87.0, 2)],
        )

        book = Workbook(write_only=True)
        source_sheet = book.create_sheet("Данные")
        headers = ["Дата", "ВЛО, Па", "ФГО+ФТО, Па", "N, МВт"]
        source_sheet.append(headers)
        for row in values.itertuples():
            source_sheet.append([
                row.date.to_pydatetime(), row.vlo, row.fgo_fto, row.power_n,
            ])
        write_pressure_sheet(
            book, headers, 0, len(values) + 1,
            PressureChartData(values, periods, None, (), values, deltas),
        )
        output = io.BytesIO()
        book.save(output)
        with ZipFile(output) as archive:
            ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
                  "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            chart_xml = ET.fromstring(archive.read("xl/charts/chart2.xml"))
            labels = chart_xml.findall(".//c:dLbl/c:tx/c:rich", ns)
            self.assertEqual(len(labels), 12)
            texts = [''.join(label.itertext()) for label in labels]
            self.assertFalse(any('п.п.' in text or 'нм³/(' in text for text in texts))
            for label in labels:
                for style in label.findall("a:p/a:pPr/a:defRPr", ns):
                    self.assertEqual(style.get("sz"), "1600")
                    self.assertEqual(style.get("b"), "1")
        output.seek(0)
        saved = load_workbook(output)
        chart_sheet = saved["Графики"]
        self.assertEqual(len(chart_sheet._charts), 2)
        degradation_chart = chart_sheet._charts[1]
        self.assertEqual(len(degradation_chart._charts), 2)
        self.assertEqual(len(degradation_chart.series), 3 * 3 + 4 * 3)
        self.assertEqual(len(degradation_chart._charts[1].series), 3)
        self.assertEqual(degradation_chart.anchor._from.col, 25)  # Z2
        self.assertEqual(degradation_chart.anchor._from.row, 1)
        self.assertEqual(degradation_chart.y_axis.scaling.min, 0)
        self.assertGreater(degradation_chart.y_axis.scaling.max, 1700)
        self.assertEqual(degradation_chart._charts[1].y_axis.scaling.min, 65)
        self.assertEqual(degradation_chart._charts[1].y_axis.scaling.max, 100)
        self.assertEqual(
            from_excel(degradation_chart.x_axis.scaling.min).date(),
            pd.Timestamp("2025-11-01").date(),
        )
        self.assertEqual(
            from_excel(degradation_chart.x_axis.scaling.max).date(),
            pd.Timestamp("2026-05-01").date(),
        )
        self.assertIsNotNone(degradation_chart.y_axis.majorGridlines)
        self.assertIsNotNone(degradation_chart.y_axis.minorGridlines)
        self.assertEqual(chart_sheet["Z39"].value, "Период")
        self.assertEqual(chart_sheet["Z40"].value, "Период 1")
        data_sheet = saved[DATA_SHEET_NAME]
        self.assertEqual(data_sheet.sheet_state, "visible")
        self.assertEqual(data_sheet.freeze_panes, "A6")
        self.assertEqual(data_sheet["A6"].value, values.iloc[0]["date"])
        self.assertEqual(data_sheet["E6"].value, 86.2)
        self.assertIsNone(chart_sheet["BJ2"].value)
        self.assertIsNone(chart_sheet["BN2"].value)
        expected_ranges = [(6, 7), (15, 16), (24, 25)]
        for group in degradation_chart._charts:
            metrics = [series for series in group.series if series.trendline is not None]
            self.assertEqual(len(metrics), 9 if group is degradation_chart else 3)
            for index, series in enumerate(metrics):
                first, last = expected_ranges[index % 3]
                self.assertEqual(series.xVal.numRef.f, f"'{DATA_SHEET_NAME}'!$A${first}:$A${last}")
                self.assertEqual(len(series.xVal.numRef.numCache.pt), 2)
                self.assertEqual(len(series.yVal.numRef.numCache.pt), 2)
                self.assertEqual(series.trendline.trendlineType, "linear")
                self.assertFalse(series.trendline.dispEq)
                self.assertFalse(series.trendline.dispRSqr)
        self.assertEqual(chart_sheet.page_setup.fitToWidth, 2)

        # Отсутствие каналов перепада не должно убирать диаграмму деградации.
        without_pressure = Workbook(write_only=True)
        without_pressure.create_sheet("Данные").append(["Дата"])
        write_pressure_sheet(
            without_pressure, ["Дата"], 0, len(values) + 1,
            PressureChartData(values, periods, None, (), values, deltas),
        )
        standalone_output = io.BytesIO()
        without_pressure.save(standalone_output)
        standalone_output.seek(0)
        standalone = load_workbook(standalone_output)
        self.assertEqual(len(standalone["Графики"]._charts), 1)
        self.assertIn(DATA_SHEET_NAME, standalone.sheetnames)
        self.assertLess(standalone["Графики"].max_column, 62)

    def test_low_vna_and_high_fuel_fit_their_axes_without_changing_values(self):
        values = pd.DataFrame({
            "period": [1, 1, 2, 2],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-03-01", "2026-03-02"]),
            "vna": [95.2, 95.3, 1.2, 1.3],
            "power": [154., 155., 69., 70.],
            "fuel_specific": [303., 304., 395., 1343.],
            "eta_gtu": [34., 34.2, 26., 27.],
            "excel_row": [5, 6, 100, 101],
        })
        original = values.copy(deep=True)
        periods = values.groupby("period").date.agg(date_start="min", date_end="max").reset_index()
        deltas = pd.DataFrame({"Период": [1, 2], "ΔNприв": [1., 1.],
                               "Δbприв": [-1., -2.], "Δη, п.п.": [.2, 1.]})
        before = deltas.copy(deep=True)
        book = Workbook(write_only=True)
        book.create_sheet("Данные").append(["Дата"])
        write_pressure_sheet(book, ["Дата"], 0, 5,
                             PressureChartData(values, periods, None, (), values, deltas))
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        saved = load_workbook(output)
        chart = saved["Графики"]._charts[0]
        self.assertEqual(chart._charts[1].y_axis.scaling.min, 0)
        self.assertEqual(chart._charts[1].y_axis.scaling.max, 100)
        self.assertGreater(chart.y_axis.scaling.max, 1343)
        self.assertEqual(saved[DATA_SHEET_NAME]["E15"].value, 1.2)
        self.assertEqual(saved[DATA_SHEET_NAME]["C16"].value, 1343.)
        self.assertEqual(saved[DATA_SHEET_NAME]["F15"].value, 100)
        labels = [series.tx.v for series in chart.series if series.xVal.numLit is not None]
        self.assertEqual(labels.count("ΔηГТУ = ↓ отсутствует"), 2)
        self.assertEqual(labels.count("ΔNприв = ↓ отсутствует"), 2)
        self.assertEqual(labels.count("Δbприв = ↑ отсутствует"), 2)
        upper_label = next(s for s in chart.series if s.tx.v == '95,0 % ≤ ВНА < 96,0 %')
        upper_position = upper_label.yVal.numLit.pt[0].v / chart.y_axis.scaling.max
        self.assertGreater(abs(upper_position - .9525), .05)
        for series in chart.series:
            if series.xVal.numLit is not None:
                for point in series.yVal.numLit.pt:
                    self.assertTrue(chart.y_axis.scaling.min < point.v < chart.y_axis.scaling.max)
        pd.testing.assert_frame_equal(values, original)
        pd.testing.assert_frame_equal(deltas, before)

    def test_missing_metrics_and_single_points_do_not_get_invalid_trends(self):
        values = pd.DataFrame({"period": [1, 1, 2],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-03-01"]),
            "vna": [85.2, 85.3, 1.2], "power": [100., 99., 70.],
            "fuel_specific": [float('nan'), 300., float('nan')],
            "eta_gtu": [30., 30., 28.]})
        periods = values.groupby("period").date.agg(date_start="min", date_end="max").reset_index()
        book = Workbook(write_only=True)
        book.create_sheet("Данные").append(["Дата"])
        write_pressure_sheet(book, ["Дата"], 0, 4,
                             PressureChartData(values, periods, None, (), values, None))
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        saved = load_workbook(output)
        chart = saved["Графики"]._charts[0]
        series = [s for group in chart._charts for s in group.series if s.xVal.numRef is not None]
        self.assertEqual(sum(s.trendline is not None for s in series), 3)
        fuel = [s for s in series if s.tx.v == 'bприв']
        self.assertEqual(len(fuel), 1)
        self.assertIsNone(fuel[0].trendline)
        self.assertEqual([p.idx for p in fuel[0].yVal.numRef.numCache.pt], [1])
        self.assertIsNone(saved[DATA_SHEET_NAME]['C6'].value)

    def test_degradation_labels_show_only_adverse_changes(self):
        for symbol, direction in [('ΔNприв', -1), ('Δbприв', 1), ('ΔηГТУ', -1)]:
            arrow = '↑' if direction == 1 else '↓'
            for improvement in (0., -direction, direction * .0001):
                self.assertEqual(_delta_label(symbol, improvement, '%', direction=direction),
                                 f'{symbol} = {arrow} отсутствует')
            self.assertEqual(_delta_label(symbol, direction * 1.25, '%', direction=direction),
                             f'{symbol} = {arrow}1,25 %')
            self.assertEqual(_delta_label(symbol, None, '%', direction=direction),
                             f'{symbol} = нет данных')


if __name__ == "__main__":
    unittest.main()
