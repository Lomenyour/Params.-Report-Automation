"""Годовое приведение экономики, проценты Word и строка GUI."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from app import delta_table_for_display  # noqa: E402
from economics import calculate_economics  # noqa: E402
from reporting import _delta_context, build_report_data  # noqa: E402


class AnnualizedEconomicsTest(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame([
            {
                "period": period,
                "date": pd.Timestamp(f"2026-01-{period:02d}") + pd.Timedelta(hours=offset),
                "hours": first_hour + offset,
                "power": 100.0 - offset,
                "fuel_specific": 300.0 + offset,
                "vna": 86.5,
            }
            for period, first_hour in ((1, 1.0), (2, 10.0))
            for offset in range(4)
        ])
        self.periods = pd.DataFrame([
            {
                "period": period,
                "date_start": rows["date"].iloc[0],
                "date_end": rows["date"].iloc[-1],
            }
            for period, rows in self.data.groupby("period")
        ])
        self.deltas = pd.DataFrame({
            "Период": [1, 2],
            "Часы начала": [1.0, 10.0],
            "Часы конца": [4.0, 13.0],
            "ΔNприв": [-3.0, -3.0],
            "ΔNприв, %": [-3.0, -3.0],
            "Δbприв": [3.0, 3.0],
            "Δbприв, %": [1.0, 1.0],
        })
        self.deltas.attrs["weighted_summary"] = {
            "delta_n": 3.0,
            "delta_n_percent": 3.0,
            "delta_b": 3.0,
            "delta_b_percent": 1.0,
        }

    def calculate(self, delta_table=None):
        return calculate_economics(
            self.data,
            self.periods,
            gas_price_rub_per_m3=2.0,
            electricity_price_rub_per_mwh=100.0,
            electricity_cost_rub_per_mwh=20.0,
            power_threshold=80.0,
            vna_data=self.data,
            delta_table=delta_table,
        )

    def test_annualized_rows_use_accepted_period_hours_and_keep_total(self):
        result = self.calculate(self.deltas)
        table = result["table"]
        self.assertEqual(result["total_period_hours"], 6.0)
        self.assertEqual(len(table), 5)
        total = table.loc[table["Период"] == "ИТОГО"].iloc[0]
        self.assertGreater(total["Недовыработка, МВт·ч"], 0)
        self.assertGreater(total["Перерасход, нм³"], 0)
        factor = 8760.0 / 6.0
        self.assertAlmostEqual(
            result["annualized"]["underproduction_mwh"],
            total["Недовыработка, МВт·ч"] * factor,
        )
        self.assertAlmostEqual(
            result["annualized"]["underproduction_rub"],
            total["Недовыработка, руб"] * factor,
        )
        self.assertAlmostEqual(
            result["annualized"]["fuel_overrun_nm3"],
            total["Перерасход, нм³"] * factor,
        )
        self.assertAlmostEqual(
            result["annualized"]["fuel_overrun_rub"],
            total["Перерасход, руб"] * factor,
        )
        self.assertTrue(pd.isna(table.iloc[-2]["Недовыработка, МВт·ч"]))
        self.assertTrue(pd.isna(table.iloc[-1]["Перерасход, нм³"]))
        self.assertAlmostEqual(
            total["Общие издержки, руб"],
            total["Недовыработка, руб"] + total["Перерасход, руб"],
        )

    def test_zero_duration_has_no_annualized_number(self):
        invalid = self.deltas.copy()
        invalid.loc[0, "Часы конца"] = invalid.loc[0, "Часы начала"]
        result = self.calculate(invalid)
        self.assertTrue(np.isnan(result["total_period_hours"]))
        self.assertTrue(np.isnan(result["annualized"]["fuel_overrun_nm3"]))

    def test_word_tags_and_gui_footer(self):
        result = self.calculate(self.deltas)
        context = build_report_data(
            source_data=self.data,
            rh_data=self.data,
            periods_df=self.periods,
            boundary_table=None,
            delta_table=self.deltas,
            vna_results=[],
            economics_result=result,
            nominal_hours={},
            gas_tariff=2000.0,
            electricity_tariff=100.0,
            electricity_cost=20.0,
        )
        self.assertEqual(set(context["economics"]["annualized"]), {
            "fuel_overrun_nm3", "fuel_overrun_rub",
            "underproduction_mwh", "underproduction_rub",
        })
        self.assertEqual(context["weighted_deltas"]["b_priv_percent"], "1,00")
        self.assertEqual(context["periods"][0]["deltas"]["n_priv_percent"], "3,00")
        self.assertEqual(_delta_context({"Δbприв, %": 0.1})["b_priv_percent"], "0,10")
        shown = delta_table_for_display(self.deltas)
        self.assertEqual(len(shown), 3)
        self.assertEqual(shown.iloc[-1]["ΔNприв"], 3.0)
        self.assertEqual(shown.iloc[-1]["Δbприв, %"], 1.0)
        self.assertEqual(len(self.deltas), 2)


if __name__ == "__main__":
    unittest.main()
