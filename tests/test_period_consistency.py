"""Ручные даты не должны менять состав одинакового рабочего периода."""

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_periods(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PeriodConsistencyTest(unittest.TestCase):
    def test_auto_and_manual_select_same_working_rows(self):
        dates = pd.date_range("2026-01-01", periods=13, freq="30min")
        data = pd.DataFrame({
            "date": dates,
            "power": [90, 91, 0, 92, np.nan, 93, 0, 0, 0, 88, 89, 90, 91],
            "fuel_specific": np.arange(13, dtype=float),
            "vna": [86.5] * 13,
            "excel_row": np.arange(2, 15),
        })

        for name, path in (
            ("source_periods", ROOT / "scr" / "periods.py"),
            ("app_periods", ROOT / "app" / "src" / "periods.py"),
        ):
            with self.subTest(name=name):
                periods = load_periods(path, name)
                periods.GAP_SIZE = 3
                periods.WORK_CONFIRM_SIZE = 2
                auto = periods.detect_periods(data)
                manual = periods.apply_period_overrides(data, [
                    ("01-01-2026 00:00", "01-01-2026 02:30"),
                    ("01-01-2026 04:30", "01-01-2026 05:00"),
                    ("01-01-2026 05:30", "01-01-2026 06:00"),
                ])

                # В ручном режиме второй период разбит, но состав первого
                # должен полностью совпадать, в том числе для ВНА и bприв.
                pd.testing.assert_frame_equal(
                    auto.loc[auto["period"] == 1].reset_index(drop=True),
                    manual.loc[manual["period"] == 1].reset_index(drop=True),
                )
                self.assertEqual(
                    manual.loc[manual["period"] > 0, "excel_row"].tolist(),
                    [2, 3, 5, 7, 11, 12, 13, 14],
                )
                self.assertEqual(
                    manual.loc[manual["period"] > 0, "period"].tolist(),
                    [1, 1, 1, 1, 2, 2, 3, 3],
                )


if __name__ == "__main__":
    unittest.main()
