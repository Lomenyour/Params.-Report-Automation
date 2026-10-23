"""Номинальная наработка и распределение учитывают только принятые периоды."""

import contextlib
import io
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
import periods  # noqa: E402
from RH_raschet import calculate_nominal_hours, main as run_rh  # noqa: E402


class NominalPeriodScopeTest(unittest.TestCase):
    def test_manual_period_excludes_other_rows_from_distribution_and_hours(self):
        dates = pd.date_range("2026-01-01", periods=12, freq="30min")
        source = pd.DataFrame({
            "date": dates,
            "power": [100.0] * 4 + [80.0] * 4 + [100.0] * 4,
            "fuel": [1000.0] * 12,
            "vna": [90.0] * 4 + [85.0] * 4 + [90.0] * 4,
            "hours": [index * 0.5 for index in range(12)],
        })
        previous = periods.PERIOD_OVERRIDES
        periods.PERIOD_OVERRIDES = [(
            dates[4].strftime("%d-%m-%Y %H:%M"),
            dates[7].strftime("%d-%m-%Y %H:%M"),
        )]
        try:
            tables = {}
            with contextlib.redirect_stdout(io.StringIO()):
                selected, accepted, _, _ = run_rh(
                    source, show_plots=False, output_tables=tables
                )
        finally:
            periods.PERIOD_OVERRIDES = previous

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(selected), 4)
        summary = calculate_nominal_hours(selected)
        self.assertEqual(summary["distribution"]["Записей"].sum(), 4)
        self.assertEqual(summary["power_hours"], 2.0)
        self.assertEqual(summary["vna_hours"], 2.0)
        shown = tables["nominal_hours"].iloc[0]
        self.assertEqual(shown["Часы Nприв выше порога"], 2.0)
        self.assertEqual(shown["Часы ВНА выше 80 %"], 2.0)


if __name__ == "__main__":
    unittest.main()
