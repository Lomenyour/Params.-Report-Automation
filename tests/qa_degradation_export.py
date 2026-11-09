"""Opt-in comparison of degradation exports from saved, unchanged local snapshots.

py -X utf8 tests/qa_degradation_export.py --baseline-ref 08e1050
  --snapshot data/qa_20261106/izhevsk_ready/snapshot.pkl --output data/qa_degradation
No input books, profiles, or snapshots are overwritten.
"""
import argparse
import copy
import json
from pathlib import Path
import pickle
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scr'))
import pandas as pd
from degradation_chart import DATA_SHEET_NAME, prepare_degradation_plot
from RH_raschet import build_boundary_table
from reporting import _pressure_delta_context, generate_report
from result_export import save_result_workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='append', type=Path, required=True)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = types.ModuleType('qa_before_degradation')
    sys.modules[baseline.__name__] = baseline
    source = subprocess.check_output(['git', 'show', f'{args.baseline_ref}:scr/degradation_chart.py'],
                                     cwd=ROOT, text=True, encoding='utf-8')
    exec(compile(source, 'baseline_degradation_chart.py', 'exec'), baseline.__dict__)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
          's': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    for path in args.snapshot:
        with path.open('rb') as stream:
            snapshot = pickle.load(stream)
        chart = snapshot.pressure_chart
        old = baseline.prepare_degradation_plot(chart.degradation_values, chart.periods,
                                                chart.degradation_deltas)
        new = prepare_degradation_plot(chart.degradation_values, chart.periods,
                                       chart.degradation_deltas)
        pd.testing.assert_frame_equal(old.points, new.points[old.points.columns])
        assert old.periods == new.periods
        snapshot_before = pickle.dumps(snapshot)
        output = args.output / f'{path.parent.name}.xlsx'
        save_result_workbook(snapshot.data, snapshot.sections, output,
            pressure_chart=chart, correction_sheet=snapshot.correction_sheet,
            gas_passport=snapshot.gas_passport, correction_profile=snapshot.correction_profile,
            book_profile=snapshot.book_profile)
        assert pickle.dumps(snapshot) == snapshot_before, 'Export changed the snapshot'
        report_data = copy.deepcopy(snapshot.report_data)
        boundaries = build_boundary_table(chart.rh_values, chart.periods)
        for period in report_data['periods']:
            period['boundary']['delta'] = _pressure_delta_context(
                boundaries.attrs['pressure_deltas_pa'].get(period['number']))
        generate_report(report_data, output_path=output.with_suffix('.docx'))
        with ZipFile(output) as archive:
            charts = [ET.fromstring(archive.read(name)) for name in archive.namelist()
                      if name.startswith('xl/charts/chart') and name.endswith('.xml')]
            diagram = next(root for root in charts if any(
                'Nприв, МВт' == s.findtext('c:tx/c:v', namespaces=ns)
                for s in root.findall('.//c:ser', ns)))
            main_axis = next(axis for axis in diagram.findall('.//c:valAx', ns)
                             if axis.find('c:axPos', ns).get('val') == 'l')
            other_axis = next(axis for axis in diagram.findall('.//c:valAx', ns)
                              if axis.find('c:axPos', ns).get('val') == 'r')
            series = [s for s in diagram.findall('.//c:ser', ns)
                      if s.find('c:xVal/c:numRef', ns) is not None]
            trend_count = 0
            for item in series:
                title = item.findtext('c:tx/c:v', namespaces=ns)
                key = {'Nприв, МВт': 'power', 'bприв': 'fuel_specific',
                       'ηГТУ, %': 'eta_gtu', 'ВНА, %': 'vna'}[title]
                formula = item.findtext('c:xVal/c:numRef/c:f', namespaces=ns)
                assert formula.startswith(f"'{DATA_SHEET_NAME}'!$A$")
                x = [float(v.text) for v in item.findall('c:xVal//c:pt/c:v', ns)]
                y = [float(v.text) for v in item.findall('c:yVal//c:pt/c:v', ns)]
                first, last = min(x), max(x)
                match = [number for number, points in new.points.groupby('period')
                         if len(points) == len(x) and
                         abs((pd.Timestamp('1899-12-30') + pd.Timedelta(days=first))
                             .timestamp() - points.date.min().timestamp()) < .01 and
                         abs((pd.Timestamp('1899-12-30') + pd.Timedelta(days=last))
                             .timestamp() - points.date.max().timestamp()) < .01]
                assert len(match) == 1, 'Series crosses period boundaries'
                points = new.points.loc[new.points.period == match[0], key].dropna()
                assert len(points) == len(y)
                assert all(abs(a-b) <= 1e-9 * max(1., abs(a)) for a,b in zip(points, y))
                axis = other_axis if key == 'vna' else main_axis
                low = float(axis.find('c:scaling/c:min', ns).get('val'))
                high = float(axis.find('c:scaling/c:max', ns).get('val'))
                assert all(low <= value <= high for value in y), 'Axis clips data'
                trend_count += item.find('c:trendline', ns) is not None
        report = dict(snapshot=str(path), output=str(output),
                      points_unchanged=len(new.points), periods=len(new.periods),
                      data_series=len(series), linear_trends=trend_count,
                      snapshot_unchanged=True,
                      pressure_deltas=[p['boundary']['delta'] for p in report_data['periods']])
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    (args.output/'verification.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
