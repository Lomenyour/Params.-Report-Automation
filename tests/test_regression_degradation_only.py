"""Основные дельты после отсечки, исходные изменения и прежняя сводка."""
import contextlib
import io
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from app import delta_table_for_display
from economics import calculate_economics
from RH_raschet import build_boundary_delta_table, build_weighted_delta_summary
from reporting import _delta_context


class RegressionDegradationOnlyTest(unittest.TestCase):
    def setUp(self):
        rows = []
        for period, duration, delta_n, delta_b in ((1, 1., 4., -2.),
                                                  (2, 2., -2., 4.),
                                                  (3, 3., 2., 2.)):
            for offset in np.arange(0., duration + .25, .5):
                rows.append({
                    "period": period,
                    "date": pd.Timestamp(2026, period, 1) + pd.Timedelta(hours=offset),
                    "hours": (period - 1) * 10. + offset,
                    "power": 100. + delta_n * offset / duration,
                    "fuel_specific": 300. + delta_b * offset / duration,
                    "eta_gtu": 30. - .1 * offset,
                    "vna": 86.5,
                })
        self.values = pd.DataFrame(rows)
        self.periods = pd.DataFrame([
            {"period": number, "date_start": group.date.min(), "date_end": group.date.max()}
            for number, group in self.values.groupby("period")
        ])

    def calculate(self, vna=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return build_boundary_delta_table(self.values, self.periods,
                                              self.values if vna is None else vna)

    def test_main_columns_only_degradation_and_raw_columns_keep_changes(self):
        original = self.values.copy(deep=True)
        table = self.calculate()
        self.assertEqual(table["ΔNприв"].tolist(), [0., -2., 0.])
        self.assertEqual(table["Δbприв"].tolist(), [0., 4., 2.])
        self.assertEqual(table["ΔNприв до отсечки"].tolist(), [4., -2., 2.])
        self.assertEqual(table["Δbприв до отсечки"].tolist(), [-2., 4., 2.])
        self.assertEqual(table["ΔNприв, %"].tolist(), [0., -2., 0.])
        self.assertEqual(table["Δbприв, %"].tolist(), [0., 1.33, .67])
        self.assertEqual(table["Δη, п.п."].tolist(), [-.1, -.2, -.3])
        pd.testing.assert_frame_equal(self.values, original)
        screen = delta_table_for_display(table)
        pd.testing.assert_frame_equal(screen.iloc[:3].reset_index(drop=True),
                                      table, check_dtype=False)
        self.assertEqual(_delta_context(table.iloc[0])["n_priv"], "0")
        self.assertEqual(_delta_context(table.iloc[0])["b_priv"], "0")
        self.assertEqual(_delta_context(table.iloc[1])["n_priv"], "2")

    def test_weighted_summary_and_economics_are_unchanged(self):
        table = self.calculate()
        legacy = table.copy(deep=True)
        legacy["ΔNприв"] = legacy["ΔNприв до отсечки"]
        legacy["Δbприв"] = legacy["Δbприв до отсечки"]
        before = build_weighted_delta_summary(legacy)
        after = table.attrs["weighted_summary"]
        for key in before:
            self.assertAlmostEqual(before[key], after[key], places=10)
        self.assertAlmostEqual(after["hours"], 6.)
        self.assertAlmostEqual(after["delta_n"], 4. / 6.)
        self.assertAlmostEqual(after["delta_b"], 14. / 6.)
        results = [calculate_economics(self.values, self.periods,
                   gas_price_rub_per_m3=7.773, electricity_price_rub_per_mwh=2253.66,
                   electricity_cost_rub_per_mwh=1200., power_threshold=80.,
                   vna_data=self.values, delta_table=delta) for delta in (legacy, table)]
        pd.testing.assert_frame_equal(results[0]["table"], results[1]["table"])
        pd.testing.assert_frame_equal(results[0]["row_losses"], results[1]["row_losses"])

    def test_missing_regression_stays_missing_instead_of_zero(self):
        vna = self.values.copy(deep=True)
        vna.loc[vna.period == 1, "power"] = np.nan
        table = self.calculate(vna)
        for column in ("ΔNприв", "ΔNприв, %", "ΔNприв до отсечки"):
            self.assertTrue(pd.isna(table.loc[0, column]))


if __name__ == "__main__":
    unittest.main()
