import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
from data_assembly import SensorMapping
from source_workbook import prepare_source_update, save_source_workbook, validate_destination
from workbook_profile import BookSetup, WorkbookLayout


class SourceWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.book = self.root/'original.xlsm'
        self.source = self.root/'raw.csv'
        self.book.write_bytes(b'original')
        self.source.write_text('measurements', encoding='utf-8')
        stat = self.book.stat()
        self.dates = pd.to_datetime(['2026-01-01 00:00', '2026-01-01 01:00'])
        self.layout = WorkbookLayout(self.book, 1, dict(A='Часы', B='Дата', C='Измерение', D='Формула'),
            pd.DataFrame(dict(A=[123., 124., None], B=[*self.dates, None], C=[1., 2., None], D=[2., 4., 6.])))
        self.setup = BookSetup('izhevsk_tec', '1', [
            dict(column='A', role='hours_input', kind='service', header='Часы', unit='ч'),
            dict(column='B', role='date', kind='service', header='Дата', unit=''),
            dict(column='C', role='power', kind='measured', header='Измерение', unit='МВт'),
            dict(column='D', role='', kind='computed', header='Формула', unit='')], {}, {},
            (str(self.book.resolve()), stat.st_mtime_ns, stat.st_size), 1)
        changed = pd.to_datetime(['2026-01-01 00:00', '2026-01-01 00:30', '2026-01-01 01:30'])
        self.assembled = SimpleNamespace(
            changed_dates=changed, values=pd.DataFrame(dict(C=[5., 6., float('nan')]), index=changed),
            headers=dict(self.layout.headers), imported_rows=3, overlap_rows=1,
            invalid_sensor_values={}, source_diagnostics=dict(skipped_rows=2))
        self.mappings = [SensorMapping('CH', 'C')]

    def prepare(self):
        with patch('source_workbook.read_layout', return_value=self.layout), \
             patch('source_workbook.assemble_sensor_data', return_value=self.assembled):
            return prepare_source_update(self.book, self.source, 'CSV', self.mappings,
                setup=self.setup, station_id='izhevsk_tec', unit='1', repository=object())

    def test_plan_inserts_before_footer_and_keeps_physical_old_rows(self):
        plan = self.prepare()
        self.assertEqual(plan['inserts'], [dict(before=4, count=1), dict(before=5, count=1)])
        self.assertEqual(plan['original_rows'], [3, 5])
        self.assertEqual(plan['new_rows'], [4, 6])
        self.assertEqual(plan['columns'], [3])
        self.assertEqual([item['row'] for item in plan['changes']], [3, 4, 6])
        self.assertEqual(plan['changes'][-1]['values'], [None])
        self.assertEqual(plan['carry_columns'], [4])
        self.assertEqual(self.layout.values['A'].tolist()[:2], [123., 124.])
        json.dumps(plan, allow_nan=False)

    def test_deferred_is_a_new_raw_column_and_ignored_is_not_written(self):
        self.mappings += [SensorMapping('NEW', '', status='deferred'), SensorMapping('SKIP', '', status='ignored')]
        self.assembled.headers['E'] = 'До уточнения: NEW'
        self.assembled.values['E'] = ['text', None, 4.]
        plan = self.prepare()
        self.assertEqual(plan['columns'], [3, 5])
        self.assertEqual(plan['headers'], [dict(column=5, label='До уточнения: NEW')])

    def test_rejects_changed_book_stamp(self):
        self.book.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'изменилась'):
            self.prepare()

    def test_rejects_duplicate_unordered_and_internal_undated_rows(self):
        for values, message in (([self.dates[0], self.dates[0], None], 'повторов'),
                                ([self.dates[1], self.dates[0], None], 'возрастанию'),
                                ([self.dates[0], None, self.dates[1]], 'без даты')):
            with self.subTest(values=values):
                self.layout.values['B'] = values
                with self.assertRaisesRegex(ValueError, message):
                    self.prepare()

    def test_does_not_round_wrong_times_onto_valid_measurements(self):
        self.layout.values.loc[0, 'B'] = pd.Timestamp('2026-01-01 00:01')
        with self.assertRaisesRegex(ValueError, 'получасовые'):
            self.prepare()

    def test_rejects_all_ignored_and_service_overwrite(self):
        self.mappings = [SensorMapping('CH', '', status='ignored')]
        with self.assertRaisesRegex(ValueError, 'Нет каналов'):
            self.prepare()
        self.mappings = [SensorMapping('CH', 'A')]
        with self.assertRaisesRegex(ValueError, 'наработку'):
            self.prepare()

    def test_destination_preserves_input_and_original_format(self):
        for path in (self.book, self.source, self.root/'result.xlsx'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_destination(self.book, self.source, path)
        self.assertEqual(validate_destination(self.book, self.source, self.root/'result.xlsm'),
                         self.root/'result.xlsm')

    def test_excel_failure_does_not_replace_existing_destination(self):
        destination = self.root/'result.xlsm'
        destination.write_bytes(b'previous result')
        with patch('source_workbook.prepare_source_update', return_value=self.prepare()), \
             patch('source_workbook.subprocess.run', return_value=SimpleNamespace(returncode=1)), \
             patch('source_workbook.subprocess.CREATE_NO_WINDOW', 0, create=True):
            with self.assertRaisesRegex(RuntimeError, 'Excel'):
                save_source_workbook(self.book, self.source, 'CSV', self.mappings, destination,
                    setup=self.setup, station_id='izhevsk_tec', unit='1', repository=object())
        self.assertEqual(destination.read_bytes(), b'previous result')
        self.assertEqual(self.book.read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('.gtu-source-*')))


if __name__ == '__main__':
    unittest.main()
