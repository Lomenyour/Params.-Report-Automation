"""TOP-1 каждого периода определяет собственную выборку для Excel-графика."""
import io
import sys
import unittest
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from compressor_degradation_chart import prepare_compressor_plots  # noqa: E402
from pressure_chart import PressureChartData, write_pressure_sheet  # noqa: E402


class CompressorDegradationChartTest(unittest.TestCase):
    def test_period_filters_and_exported_charts(self):
        records = []
        results = []
        for period in range(1, 4):
            first = pd.Timestamp(2026, period, 1)
            for index, (vna, t, pressure) in enumerate((
                (86.21, 10.1, 990.1),
                (86.29, 10.4, 990.4),
                (86.31, 10.2, 990.2),  # вне TOP-1 ВНА
                (86.22, 11.0, 990.2),  # вне температуры
                (86.23, 10.2, 991.0),  # вне давления
            )):
                records.append({
                    "period": period, "date": first + pd.Timedelta(hours=index),
                    "vna": vna, "t": t, "p": pressure, "tkk": 370.0,
                    "pkk": 13.0, "pi_k": 13.1 + index / 10,
                    "eta_compressor": 84.01 + index / 100,
                    "vlo": 200.0, "fgo_fto": 225.0, "power_n": 85.0,
                })
            table = pd.DataFrame([{
                "vna_interval": "86.2-86.3", "t_1": 10.1, "t_2": 10.4,
                "p_1": 990.1, "p_2": 990.4,
                "date_1": first, "date_2": first + pd.Timedelta(hours=1),
                "eta_1": 84.01, "eta_2": 84.02,
                "pi_k_1": 13.1, "pi_k_2": 13.2,
            }])
            table.attrs["period_number"] = period
            results.append(table)
        values = pd.DataFrame(records)
        periods = pd.DataFrame([{
            "period": period,
            "date_start": pd.Timestamp(2026, period, 1),
            "date_end": pd.Timestamp(2026, period, 1, 4),
        } for period in range(1, 4)])

        plots = prepare_compressor_plots(values, periods, results)
        self.assertEqual([len(plot.points) for plot in plots], [2, 2, 2])
        self.assertEqual(plots[0].points["pi_k"].tolist(), [13.1, 13.2])
        self.assertEqual(plots[0].points["eta"].round(2).tolist(), [84.01, 84.02])

        book = Workbook(write_only=True)
        data_sheet = book.create_sheet("Данные")
        headers = ["Дата", "ВЛО, Па", "ФГО+ФТО, Па", "N, МВт"]
        data_sheet.append(headers)
        for row in values.itertuples(index=False):
            data_sheet.append([row.date.to_pydatetime(), row.vlo,
                               row.fgo_fto, row.power_n])
        write_pressure_sheet(
            book, headers, 0, len(values) + 1,
            PressureChartData(values, periods, None, vna_top10=results,
                              degradation_values=values),
        )
        output = io.BytesIO()
        book.save(output)

        output.seek(0)
        sheet = load_workbook(output)["Графики"]
        self.assertEqual(len(sheet._charts), 5)  # Перепады, общая деградация, 3 периода
        for chart in sheet._charts[2:]:
            self.assertEqual(len(chart._charts), 2)
            self.assertEqual(len(chart.series), 1)
            self.assertIsNotNone(chart.series[0].trendline)
            self.assertIsNotNone(chart._charts[1].series[0].trendline)
        descriptions = [row[0].value for row in sheet.iter_rows(min_col=1, max_col=1)
                        if isinstance(row[0].value, str)]
        self.assertTrue(any("10.100 ≤ tнк ≤ 10.400" in text
                            for text in descriptions))
        self.assertEqual(sheet["BO2"].value, pd.Timestamp("2026-01-01"))
        self.assertAlmostEqual(sheet["BP2"].value, 84.01)
        self.assertAlmostEqual(sheet._charts[2].series[0].yVal.numRef.numCache.pt[0].v, 84.01)


if __name__ == "__main__":
    unittest.main()
