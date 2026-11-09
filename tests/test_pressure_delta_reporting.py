"""Pressure differences use the accepted boundary rows before display rounding."""
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from RH_raschet import build_boundary_table, BOUNDARY_PARAMETERS
from reporting import build_report_data, generate_report


class PressureDeltaReportingTest(unittest.TestCase):
    def setUp(self):
        self.values = pd.DataFrame({
            "period": [1, 1], "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "power": [90., 90.], "vna": [85., 85.],
            "vlo": [100.06, 100.14], "fgo": [205.26, 203.24],
            "fto": [10., 10.], "fgo_fto": [215.26, 213.24],
        })
        self.periods = pd.DataFrame([{"period": 1, "date_start": self.values.date.min(),
                                     "date_end": self.values.date.max()}])

    def report(self, boundaries):
        return build_report_data(source_data=self.values, rh_data=self.values,
            periods_df=self.periods, boundary_table=boundaries, delta_table=None,
            vna_results=[], economics_result={"table": pd.DataFrame()}, nominal_hours={},
            gas_tariff=1., electricity_tariff=1., electricity_cost=1.)

    def test_signed_differences_are_calculated_before_rounding_without_new_columns(self):
        before = self.values.copy(deep=True)
        boundaries = build_boundary_table(self.values, self.periods)
        self.assertEqual(boundaries.columns.tolist(),
            ["Период", "дата", "Порог ВНА, %", "Покрытие, %"] + [title for _, title in BOUNDARY_PARAMETERS])
        self.assertEqual(boundaries['ВЛО'].tolist(), ['100.1', '100.1'])
        self.assertAlmostEqual(boundaries.attrs['pressure_deltas_pa'][1]['vlo_pa'], .08)
        report = self.report(boundaries)
        self.assertEqual(report['periods'][0]['boundary']['delta'], {
            'vlo_pa': '0,1', 'fgo_pa': '-2', 'fto_pa': '0', 'fgo_fto_pa': '-2'})
        pd.testing.assert_frame_equal(self.values, before)

    def test_missing_channels_or_endpoints_remain_unavailable(self):
        self.values = self.values.drop(columns='fgo_fto')
        self.values.loc[1, 'fgo'] = float('nan')
        self.values.loc[1, 'fto'] = float('inf')
        report = self.report(build_boundary_table(self.values, self.periods))
        self.assertEqual(report['periods'][0]['boundary']['delta'], {
            'vlo_pa': '0,1', 'fgo_pa': '—', 'fto_pa': '—', 'fgo_fto_pa': '—'})
        self.values['power'] = 0.
        report = self.report(build_boundary_table(self.values, self.periods))
        self.assertTrue(all(value == '—' for value in report['periods'][0]['boundary']['delta'].values()))

    def test_word_tags_render_and_old_contexts_remain_compatible(self):
        report = self.report(build_boundary_table(self.values, self.periods))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            document = Document()
            document.add_paragraph('{{ periods.p1.boundary.delta.vlo_pa }} | '
                                   '{{ periods[0].boundary.delta.fgo_pa }} | '
                                   '{{ periods[0].boundary.delta.fto_pa }} | '
                                   '{{ periods[0].boundary.delta.fgo_fto_pa }}')
            template = folder / 'template.docx'
            document.save(template)
            result = generate_report(report, template, folder / 'report.docx')
            self.assertEqual(Document(result).paragraphs[0].text, '0,1 | -2 | 0 | -2')
            del report['periods'][0]['boundary']['delta']
            result = generate_report(report, template, folder / 'legacy.docx')
            self.assertEqual(Document(result).paragraphs[0].text, '— | — | — | —')


if __name__ == '__main__':
    unittest.main()
