"""The overview probe exposes exact source records and matching plot coordinates."""
from pathlib import Path
import json
import sys
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
from pressure_probe import attach_pressure_probe, pressure_probe_payload


class PressureProbeTest(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_exact_records_keep_missing_values_and_stable_duplicate_order(self):
        values = pd.DataFrame({
            'date': pd.to_datetime(['2026-01-03', '2026-01-01', None,
                                    '2026-01-01', '2026-01-02']),
            'power_n': [90., '0', 80., 7., np.inf],
            'vna': [85., np.nan, 84., 83., '81.5'],
        }, index=[9, 5, 3, 8, 1])
        before = values.copy(deep=True)
        figure, axis = plt.subplots()
        axis.plot(pd.date_range('2026-01-01', periods=3), [0, 1, 2])
        line_count = len(axis.lines)
        attach_pressure_probe(figure, axis, values)
        FigureCanvasAgg(figure).draw()
        payload = pressure_probe_payload(figure)
        self.assertEqual([point[1:] for point in payload['points']], [
            ['01.01.2026 00:00', 0., None], ['01.01.2026 00:00', 7., 83.],
            ['02.01.2026 00:00', None, 81.5], ['03.01.2026 00:00', 90., 85.],
        ])
        json.dumps(payload, allow_nan=False)
        self.assertEqual(len(axis.lines), line_count)
        pd.testing.assert_frame_equal(values, before)

    def test_overlay_matches_drawn_axes_and_date_transform(self):
        values = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=3, freq='30min'),
                               'power_n': [90., 0., 85.], 'vna': [85., 0., 84.]})
        figure, axis = plt.subplots(figsize=(10, 4))
        axis.plot(values.date, values.power_n)
        axis.twinx().plot(values.date, values.vna)
        figure.tight_layout()
        attach_pressure_probe(figure, axis, values)
        FigureCanvasAgg(figure).draw()
        payload = pressure_probe_payload(figure)
        left, top, width, height = payload['bounds']
        self.assertAlmostEqual(left, axis.bbox.x0 / figure.bbox.width)
        self.assertAlmostEqual(top, 1-axis.bbox.y1 / figure.bbox.height)
        self.assertAlmostEqual(height, axis.bbox.height / figure.bbox.height)
        for point in payload['points']:
            fraction = (point[0]-payload['x_min'])/(payload['x_max']-payload['x_min'])
            expected = axis.transData.transform((point[0], 0))[0] / figure.bbox.width
            self.assertAlmostEqual(left+width*fraction, expected)
        self.assertEqual(payload['points'][1][0], mdates.date2num(values.date.iloc[1]))

    def test_missing_measured_power_never_uses_reduced_power(self):
        values = pd.DataFrame({'date': [pd.Timestamp('2026-01-01')], 'power': [999.]})
        figure, axis = plt.subplots()
        attach_pressure_probe(figure, axis, values)
        self.assertEqual(pressure_probe_payload(figure)['points'][0][2:], [None, None])

    def test_empty_and_unrelated_figures_have_no_probe(self):
        figure, axis = plt.subplots()
        self.assertIsNone(pressure_probe_payload(figure))
        attach_pressure_probe(figure, axis, pd.DataFrame({'date': [pd.NaT]}))
        self.assertIsNone(pressure_probe_payload(figure))

    def test_fractional_seconds_and_explicit_timezone_are_not_hidden(self):
        moment = pd.Timestamp('2026-01-01 00:29:59.999999997+03:00')
        values = pd.DataFrame({'date': [moment], 'power_n': [90.], 'vna': [85.]})
        figure, axis = plt.subplots()
        attach_pressure_probe(figure, axis, values)
        point = pressure_probe_payload(figure)['points'][0]
        self.assertEqual(point[1], '01.01.2026 00:29:59.999999997 +03:00')
        self.assertEqual(point[0], mdates.date2num(moment.to_datetime64()))
