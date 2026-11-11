"""Opt-in integration run on local books; writes only to the requested output.

Example: py -X utf8 tests/qa_ready_workbook.py --book data/book.xlsx
         --output data/qa_run [--raw data/sensors.xlsx --sheet GT]
         [--baseline-vna build_test/VNA_full_before.py]
Mappings are read from existing profiles and confirmed in memory, never saved.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scr'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import app
import workbook_profile as wp
from data_assembly import SensorMapping, source_mapping_info, load_saved_mappings
from result_export import save_result_workbook
from reporting import generate_report


class Capture:
    def __init__(self, log):
        self.log, self.result, self.error = log, None, None

    def put(self, item):
        kind, value = item
        if kind == 'log':
            self.log.write(value)
        elif kind == 'period_choice':
            value['overrides'] = None
            value['event'].set()
        elif kind == 'results':
            self.result = value
        elif kind == 'error':
            self.error = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--book', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--sheet', default='')
    parser.add_argument('--baseline-vna', type=Path)
    parser.add_argument('--station-id', help='Explicit catalogue station when the filename is ambiguous')
    parser.add_argument('--unit', help='Explicit catalogue turbine number')
    parser.add_argument('--mappings', type=Path, help='Audited SensorMapping list, used in memory only')
    parser.add_argument('--column-overrides', type=Path, help='Audited column-to-field overrides, in memory only')
    parser.add_argument('--zero-tariffs', action='store_true', help='Technical trial without monetary conclusions')
    parser.add_argument('--skip-word', action='store_true', help='Do not render the user Word template')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    repository = app.get_station_repository()
    station = repository.get_station(args.station_id) if args.station_id else repository.detect_station(args.book)
    if station is None:
        raise ValueError('Станция не распознана; этот QA не подставляет чужой профиль.')
    turbine = repository.get_turbine(station.id, args.unit) if args.unit else repository.detect_turbine(args.book, station.id)
    if turbine is None:
        raise ValueError('ГТУ не распознана.')
    layout = wp.read_layout(args.book)
    rows = wp.suggestions(layout, station.id, turbine.number)
    if args.column_overrides:
        overrides = json.loads(args.column_overrides.read_text(encoding='utf-8'))
        if set(overrides) - set(layout.headers):
            raise ValueError('В уточнении указана неизвестная колонка.')
        for row in rows:
            row.update(overrides.get(row['column'], {}))
    setup = wp.confirm(layout, station.id, turbine.number, rows, save=False)
    source = setup.canonical(layout.values)
    audit = setup.audit(source)
    dates = source.date.dropna()
    audit.update(start=str(dates.min()), end=str(dates.max()),
                 nonincreasing_steps=int((dates.diff().dropna() <= pd.Timedelta(0)).sum()),
                 non_half_hour_steps=int((dates.diff().dropna() != pd.Timedelta(minutes=30)).sum()))
    # Describe raw canonical columns without cleaning, clipping or sensor repair.
    audit['numeric'] = {
        key: dict(missing=int(pd.to_numeric(source[key], errors='coerce').isna().sum()),
                  min=str(pd.to_numeric(source[key], errors='coerce').min()),
                  max=str(pd.to_numeric(source[key], errors='coerce').max()))
        for key in ('power', 'fuel', 't', 'p_atm_pa', 'vna', 'eta_compressor') if key in source}
    mappings = None
    if args.raw:
        headers, duplicates = source_mapping_info(args.raw, args.sheet, station_id=station.id)
        mappings = ([SensorMapping(**item) for item in json.loads(args.mappings.read_text(encoding='utf-8'))]
            if args.mappings else load_saved_mappings(args.book, headers, station_id=station.id,
                unit=turbine.number, target_headers=setup.import_headers(layout.headers),
                parameter_columns=setup.sensor_columns))
        if not mappings:
            raise ValueError('Нет сохранённого маппинга датчиков; QA не назначает каналы сам.')
        mappings = [item for item in mappings if item.source not in duplicates]

    tariffs = (0., 0., 0.) if args.zero_tariffs else (7.773, 2253.66, 1200.)

    def calculate(label, run_vna):
        with (args.output / f'{label}.log').open('w', encoding='utf-8') as log:
            capture = Capture(log)
            runner = SimpleNamespace(output_queue=capture, station_repository=repository,
                _build_vna_overview=app.CalculationApp._build_vna_overview)
            started = time.perf_counter()
            with patch.object(app, 'run_vna', run_vna):
                # Tariffs here are explicit QA inputs, identical for both runs.
                app.CalculationApp._calculation_worker(runner, args.book, args.raw,
                    args.sheet, mappings, *tariffs, (), station.id, turbine.number, setup)
            if capture.error or capture.result is None:
                raise AssertionError(capture.error or 'Нет результата расчёта')
            plt.close('all')
            return capture.result, time.perf_counter() - started

    baseline = None
    if args.baseline_vna:
        spec = importlib.util.spec_from_file_location('qa_baseline_vna', args.baseline_vna)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        baseline, _ = calculate('baseline', module.run_vna)
    result, seconds = calculate('current', app.run_vna)
    snapshot = result['snapshot']
    for table in result['vna_results']:
        assert len(table) <= 10
        assert table.delta_days.is_unique
        assert table['rank'].tolist() == list(range(1, len(table)+1))
    if baseline:
        for key in ('vna_periods', 'boundary_table', 'delta_table', 'economics_table'):
            pd.testing.assert_frame_equal(result[key], baseline[key])
        pd.testing.assert_frame_equal(snapshot.data.as_headered_frame(),
                                      baseline['snapshot'].data.as_headered_frame())
        for old, new in zip(baseline['vna_results'], result['vna_results'], strict=True):
            pd.testing.assert_series_equal(old.iloc[0], new.iloc[0])
    with (args.output / 'snapshot.pkl').open('wb') as stream:
        pickle.dump(snapshot, stream)
    snapshot.validate_destination(args.output / 'results.xlsx', '.xlsx')
    save_result_workbook(snapshot.data, snapshot.sections, args.output / 'results.xlsx',
        pressure_chart=snapshot.pressure_chart, correction_sheet=snapshot.correction_sheet,
        gas_passport=snapshot.gas_passport, correction_profile=snapshot.correction_profile,
        book_profile=snapshot.book_profile)
    if not args.skip_word:
        generate_report(snapshot.report_data, output_path=args.output / 'report.docx')
    if result.get('pressure_figure') is not None:
        result['pressure_figure'].savefig(args.output / 'pressure.png', dpi=130)
    report = dict(audit=audit, seconds=seconds, baseline_equal=True if baseline else None,
                  qa_tariffs=list(tariffs),
                  periods=len(result['vna_periods']), top10_rows=[len(t) for t in result['vna_results']])
    (args.output / 'qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
