"""Period boundaries follow measured N even when reduced N is missing or inflated."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
import periods
from VNA_full import run_vna


class MeasuredPowerPeriodsTest(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(periods, 'GAP_SIZE', 3),
                        patch.object(periods, 'WORK_CONFIRM_SIZE', 2),
                        patch.object(periods, 'PERIOD_OVERRIDES', [])]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.frame = pd.DataFrame({
            'date': pd.date_range('2026-01-01', periods=9, freq='30min'),
            'power_n': [90., 91., 0., 0., 0., 40., 0., 92., 93.],
            'power': [100., np.nan, 999., 999., 999., 999., 999., 1., np.nan],
            'fuel': 25000.,
            'excel_row': np.arange(2, 11),
        }, index=np.arange(100, 109))

    def test_auto_ignores_reduced_spikes_and_keeps_work_with_missing_reduced_power(self):
        before = self.frame.copy(deep=True)
        marked, summary = periods.build_periods(self.frame)
        self.assertEqual(marked.period.tolist(), [1, 1, 0, 0, 0, 0, 0, 2, 2])
        self.assertEqual(summary.records.tolist(), [2, 2])
        self.assertEqual(summary.date_start.tolist(), self.frame.date.iloc[[0, 7]].tolist())
        self.assertEqual(summary.date_end.tolist(), self.frame.date.iloc[[1, 8]].tolist())
        self.assertTrue(pd.isna(marked.power.iloc[1]))
        self.assertEqual(marked.power.iloc[2], 999.)
        pd.testing.assert_frame_equal(self.frame, before)

    def test_periods_do_not_depend_on_reduced_power_or_its_presence(self):
        expected, summary = periods.build_periods(self.frame)
        for variant in (self.frame.assign(power=0.), self.frame.assign(power=1e9),
                        self.frame.drop(columns='power')):
            marked, actual = periods.build_periods(variant)
            pd.testing.assert_series_equal(marked.period, expected.period)
            pd.testing.assert_frame_equal(actual, summary)

    def test_manual_and_auto_have_same_measured_working_rows(self):
        auto, summary = periods.build_periods(self.frame)
        intervals = list(zip(summary.date_start, summary.date_end))
        with patch.object(periods, 'PERIOD_OVERRIDES', intervals):
            manual, actual = periods.build_periods(self.frame)
        pd.testing.assert_frame_equal(auto, manual.reset_index(drop=True))
        pd.testing.assert_frame_equal(summary, actual)

    def test_missing_measured_column_is_explicit_error_in_auto_and_manual(self):
        data = self.frame.drop(columns='power_n')
        for function in (lambda: periods.detect_periods(data),
                         lambda: periods.apply_period_overrides(data, [(data.date.min(), data.date.max())])):
            with self.subTest(function=function), self.assertRaisesRegex(ValueError, 'Измеренная мощность'):
                function()

    def test_unavailable_measured_values_do_not_fall_back_to_reduced_power(self):
        for value in (np.nan, np.inf, -np.inf, 'ошибка'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'нет числовых значений измеренной мощности'):
                periods.build_periods(self.frame.assign(power_n=value, power=100.))

    def test_partial_missing_values_and_threshold_are_not_replaced(self):
        data = self.frame.iloc[:5].copy()
        data['power_n'] = [10., 10.01, np.nan, np.inf, -np.inf]
        data['power'] = 1000.
        marked, summary = periods.build_periods(data)
        self.assertEqual(marked.period.tolist(), [0, 1, 0, 0, 0])
        self.assertEqual(summary.records.tolist(), [1])

    def test_numeric_measured_text_is_used_without_rewriting_original_values(self):
        data = self.frame.iloc[:3].copy()
        data['power_n'] = ['90', '9', 'ошибка']
        original = data.copy(deep=True)
        marked, _ = periods.build_periods(data)
        self.assertEqual(marked.period.tolist(), [1, 0, 0])
        pd.testing.assert_series_equal(marked.power_n, original.power_n.reset_index(drop=True))
        pd.testing.assert_frame_equal(data, original)

    def test_vna_uses_full_periods_after_its_filter_removes_stops_and_endpoints(self):
        _, expected = periods.build_periods(self.frame)
        # The analytical subset has no long stop and omits both outer endpoints.
        filtered = self.frame.iloc[[1, 5, 7]].copy()
        original = filtered.copy(deep=True)
        with patch('VNA_full.analyze_period', return_value=(None, None)), \
                contextlib.redirect_stdout(io.StringIO()):
            marked, actual, results, figures = run_vna(
                filtered, show_plots=False, period_source=self.frame)
        self.assertEqual(marked.period.tolist(), [1, 0, 2])
        pd.testing.assert_frame_equal(actual, expected)
        self.assertEqual(results, [])
        self.assertEqual(figures, [])
        pd.testing.assert_frame_equal(filtered, original)


if __name__ == '__main__':
    unittest.main()
