"""The Word data range covers the full prepared source, including imports."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from reporting import build_report_data  # noqa: E402


class ReportingSourceDatesTest(unittest.TestCase):
    def report_source(self, source):
        accepted = pd.DataFrame([{"date": pd.Timestamp("2026-02-01 12:00")}])
        periods = pd.DataFrame([{
            "period": 1,
            "date_start": accepted.iloc[0]["date"],
            "date_end": accepted.iloc[0]["date"],
        }])
        return build_report_data(
            source_data=source,
            rh_data=accepted,
            periods_df=periods,
            boundary_table=None,
            delta_table=None,
            vna_results=[],
            economics_result={"table": pd.DataFrame()},
            nominal_hours={},
            gas_tariff=1.0,
            electricity_tariff=1.0,
            electricity_cost=1.0,
        )["source"]

    def test_dates_use_full_source_before_period_filter_and_after_merge(self):
        original = pd.DataFrame({"date": [
            pd.Timestamp("2026-02-01 12:00"),
            pd.Timestamp("2026-01-15 00:30"),
        ]})
        normal = self.report_source(original)
        self.assertEqual(normal["data_start_date"], "15.01.2026")
        self.assertEqual(normal["data_end_date"], "01.02.2026")

        merged = pd.concat([original, pd.DataFrame({"date": [
            pd.Timestamp("2026-03-10 23:30"),
            "invalid date",
        ]})], ignore_index=True)
        imported = self.report_source(merged)
        self.assertEqual(imported["data_start_date"], "15.01.2026")
        self.assertEqual(imported["data_end_date"], "10.03.2026")
        self.assertEqual(imported["invalid_date_rows"], 1)


if __name__ == "__main__":
    unittest.main()
