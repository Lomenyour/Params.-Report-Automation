"""Пара выбирается с учётом всех допусков до ранжирования TOP-10."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
import VNA_full as vna


class PairConstraintsTest(unittest.TestCase):
    def test_top10_uses_distinct_displayed_days_before_limit_and_keeps_top1(self):
        dates = pd.date_range('2026-01-01', periods=2, freq='1D')
        data = pd.DataFrame({
            'date': dates, 'vna': [86.21] * 2, 't': [10.] * 2,
            'p': [990.] * 2, 'tkk': [370.] * 2, 'pi_k': [13.] * 2,
            'eta_compressor': [80., 80.4],
        })
        base = vna._build_pair_result(
            dates, *[data[col].to_numpy() for col in
                     ('t', 'p', 'vna', 'tkk', 'pi_k', 'eta_compressor')], 0, 1)
        candidates = [dict(base, vna_from=86., vna_to=87.,
                           vna_interval=str(i), count=100-i, share_percent=50.,
                           delta_days=days, delta_eta=eta)
                      for i, (days, eta) in enumerate(
                          [(100.0001, .7), (100., .1)] * 6 +
                          [(float(day), .4) for day in range(99, 87, -1)])]
        with patch.object(vna, '_find_flexible_vna_intervals', return_value=candidates), \
                contextlib.redirect_stdout(io.StringIO()):
            table, figure = vna.analyze_period(data, 1, show_plot=False)
        plt.close(figure)
        self.assertEqual(table.delta_days.tolist(), list(range(100, 90, -1)))
        self.assertEqual(table.iloc[0].vna_interval, '0')
        self.assertEqual(table.iloc[0].delta_eta, .7)
        self.assertEqual(table['rank'].tolist(), list(range(1, 11)))

    def test_top10_can_have_fewer_rows_and_identical_eta_for_distinct_days(self):
        data = pd.DataFrame({
            'date': pd.date_range('2026-01-01', periods=4, freq='1D'),
            'vna': [86.01, 86.11, 86.21, 86.31], 't': [10.] * 4,
            'p': [990.] * 4, 'tkk': [370.] * 4, 'pi_k': [13.] * 4,
            'eta_compressor': [80.] * 4,
        })
        with contextlib.redirect_stdout(io.StringIO()):
            table, figure = vna.analyze_period(data, 1, show_plot=False)
        plt.close(figure)
        self.assertEqual(table.delta_days.tolist(), [3., 2., 1.])
        self.assertEqual(table.delta_eta.tolist(), [0., 0., 0.])

    def test_eta_limit_is_strict_at_decimal_boundary(self):
        data = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=2, freq="1D"),
            "vna": [86.21] * 2, "t": [10.] * 2, "p": [990.] * 2,
            "tkk": [370.] * 2, "pi_k": [13.] * 2,
            "eta_compressor": [80., 80.8],
        })
        self.assertEqual(vna._find_flexible_vna_intervals(data), [])

    def test_shorter_eta_compatible_pair_is_not_lost(self):
        data = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04"]),
            "vna": [86.21] * 3, "t": [10.0] * 3, "p": [990.0] * 3,
            "tkk": [370.0] * 3, "pi_k": [13.0] * 3,
            "eta_compressor": [80.0, 80.4, 81.0],
        })
        with contextlib.redirect_stdout(io.StringIO()):
            table, figure = vna.analyze_period(data, 1, show_plot=False)
        plt.close(figure)
        self.assertFalse(table.empty)
        self.assertEqual(table.iloc[0]["date_1"], data.iloc[0]["date"])
        self.assertEqual(table.iloc[0]["date_2"], data.iloc[1]["date"])
        self.assertEqual(table.iloc[0]["delta_days"], 2.0)

    def test_matches_exhaustive_search_in_overlapping_windows(self):
        rng = np.random.default_rng(214)
        for sample in range(30):
            count = 9
            data = pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=count, freq="1D"),
                "vna": 86 + rng.integers(0, 13, count) / 10 + 0.01,
                "t": rng.integers(0, 4, count) * 0.3,
                "p": 990 + rng.integers(0, 4, count) * 3.0,
                "tkk": [370.0] * count, "pi_k": [13.0] * count,
                "eta_compressor": 80 + rng.integers(0, 4, count) * 0.5,
            })
            cells = np.floor(data["vna"].to_numpy() / 0.1).astype(int)
            expected = {}
            for width in range(1, 11):
                for start in range(cells.min(), min(cells.max(), 1000 - width) + 1):
                    rows = np.flatnonzero((cells >= start) & (cells < start + width))
                    best = None
                    for position, first in enumerate(rows):
                        for last in rows[position + 1:]:
                            left, right = data.iloc[first], data.iloc[last]
                            if (abs(left.t - right.t) <= vna.MAX_DELTA_T and
                                abs(left.p - right.p) <= vna.MAX_DELTA_P and
                                abs(left.eta_compressor - right.eta_compressor) < vna.MAX_DELTA_ETA):
                                days = (right.date - left.date).days
                                best = days if best is None else max(best, days)
                    if best is not None:
                        expected[tuple(rows)] = best
            actual = {}
            for candidate in vna._find_flexible_vna_intervals(data):
                rows = tuple(np.flatnonzero(
                    (cells >= round(candidate["vna_from"] / .1)) &
                    (cells < round(candidate["vna_to"] / .1))
                ))
                actual[rows] = candidate["delta_days"]
            with self.subTest(sample=sample):
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
