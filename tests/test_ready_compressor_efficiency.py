"""Готовый КПД книги сохраняется в загрузке, TOP-10 и данных графика."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from data_loader import load_source_data, prepare_vna_data  # noqa: E402
from VNA_full import analyze_period  # noqa: E402


class ReadyCompressorEfficiencyTest(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Данные"
            sheet.append(list(raw.columns))
            for row in raw.itertuples(index=False, name=None):
                sheet.append([value.to_pydatetime() if isinstance(value, pd.Timestamp)
                              else None if pd.isna(value) else value for value in row])
            book.save(path)
            book.close()
            return load_source_data(path)

    def source(self, name="ηoi_Cprop"):
        return pd.DataFrame({
            "Дата": pd.date_range("2026-01-01", periods=3, freq="30min"),
            "Тнк, °С": [10.0] * 3, "Pатм, Па": [100000.0] * 3,
            "Pнк, Па": [200.0] * 3, "ВНА": [86.21] * 3,
            "Ткк, °С": [370.0] * 3, "Ркк, МПа": [1.3] * 3,
            "Nприв, МВт": [90.0] * 3, "Bприв, нм3/ч": [25000.0] * 3,
            name: [83.123456, np.nan, 83.523456],
        })

    def test_loader_and_top10_keep_ready_values(self):
        for name in ("ηoi_Cprop", "ηoi_cprop", "ηoi_Cprop, %"):
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                source = self.load(self.source(name))
                prepared = prepare_vna_data(source)
                self.assertEqual(len(prepared), 3)  # Пропуск КПД не удаляет строку.
                self.assertAlmostEqual(prepared.iloc[0]["eta_compressor"], 83.123456)
                table, figure = analyze_period(prepared, 1, show_plot=False)
                plt.close(figure)
                self.assertFalse(table.empty)
                self.assertAlmostEqual(table.iloc[0]["eta_1"], 83.123, places=3)
                self.assertAlmostEqual(table.iloc[0]["eta_2"], 83.523, places=3)
                self.assertAlmostEqual(table.iloc[0]["delta_eta"], 0.4)
                self.assertEqual(table.iloc[0]["date_2"], prepared.iloc[2]["date"])

    def test_missing_ready_column_is_explicit_error(self):
        with contextlib.redirect_stdout(io.StringIO()):
            source = self.load(self.source().drop(columns=["ηoi_Cprop"]))
            with self.assertRaisesRegex(ValueError, "ηoi_Cprop"):
                prepare_vna_data(source)

    def test_eta_limit_uses_ready_values(self):
        raw = self.source()
        raw["ηoi_Cprop"] = [80.0, np.nan, 81.0]
        with contextlib.redirect_stdout(io.StringIO()):
            table, figure = analyze_period(
                prepare_vna_data(self.load(raw)), 1, show_plot=False,
            )
        plt.close(figure)
        self.assertTrue(table.empty)


if __name__ == "__main__":
    unittest.main()
