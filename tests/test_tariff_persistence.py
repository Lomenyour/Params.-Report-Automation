"""Only a completed calculation updates the station's persistent tariffs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from calculation_snapshot import CalculationSnapshot
from desktop_controller import DesktopController
from station_profiles import JsonStationRepository, StationTariffs, catalog_path


class TariffStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'tariffs.json'
        self.repository = JsonStationRepository(catalog_path(), tariff_store=self.path)

    def test_station_isolation_restart_and_precision_without_catalog_edits(self):
        before = catalog_path().read_bytes()
        self.assertIsNone(self.repository.get_tariffs('izhevsk_tec'))
        first = StationTariffs(9.12345678912345, 2345.678912345, 1300.)
        second = StationTariffs(8.5, 2500., 0.)
        self.repository.save_tariffs('syz_tec', first)
        self.repository.save_tariffs('izhevsk_tec', second)
        fresh = JsonStationRepository(catalog_path(), tariff_store=self.path)
        self.assertEqual(fresh.get_tariffs('syz_tec'), first)
        self.assertEqual(fresh.get_tariffs('izhevsk_tec'), second)
        self.assertTrue(self.path.with_suffix('.json.bak').is_file())
        self.assertEqual(catalog_path().read_bytes(), before)
        self.assertEqual(JsonStationRepository(catalog_path()).get_tariffs('syz_tec').gas_rub_per_nm3, 7.773)

    def test_invalid_tariffs_unknown_stations_and_corrupt_json_are_not_saved(self):
        for invalid in (-1., float('nan'), float('inf'), True):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.repository.save_tariffs('syz_tec', StationTariffs(invalid, 2., 1.))
        with self.assertRaises(ValueError):
            self.repository.save_tariffs('unknown', StationTariffs(1., 2., 3.))
        self.assertFalse(self.path.exists())
        for content in ('broken', '{"schema_version":2,"tariffs":{}}',
                        '{"schema_version":1,"tariffs":{"syz_tec":{}}}'):
            self.path.write_text(content, encoding='utf-8')
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.repository.save_tariffs('syz_tec', StationTariffs(1., 2., 3.))
            self.assertEqual(self.path.read_text(encoding='utf-8'), content)

    def test_failed_atomic_write_preserves_saved_tariffs(self):
        old = StationTariffs(1., 2., 3.)
        self.repository.save_tariffs('syz_tec', old)
        before = self.path.read_bytes()
        with patch('json_store.os.replace', side_effect=OSError('locked')), self.assertRaises(OSError):
            self.repository.save_tariffs('syz_tec', StationTariffs(4., 5., 6.))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.repository.get_tariffs('syz_tec'), old)


_application = None


class TariffLifecycleTests(unittest.TestCase):
    def setUp(self):
        global _application
        _application = QApplication.instance() or QApplication([])
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'tariffs.json'
        self.windows = []
        self.addCleanup(self.close_windows)
        self.c = self.controller()
        self.choose(self.c)

    def controller(self):
        window = QWidget()
        c = DesktopController(window)
        c.station_repository = JsonStationRepository(catalog_path(), tariff_store=self.path)
        c.messages.showerror = Mock()
        c.messages.showwarning = Mock()
        c.messages.showinfo = Mock()
        self.windows.append((window, c))
        return c

    def close_windows(self):
        for window, c in self.windows:
            c.closed = True
            c._clear_charts()
            window.close()
            window.deleteLater()
        _application.processEvents()

    def choose(self, c, name='СызТЭЦ ГТ-11.xlsx'):
        with patch.object(c.files, 'askopenfilename', return_value=name), \
                patch.dict(c.choose_file.__func__.__globals__, load_chart_events=Mock(return_value=())):
            c.choose_file()

    def snapshot(self, tariffs=None):
        return CalculationSnapshot(None, [], None, {}, (), 'qa', tariffs_station_id='syz_tec',
            station_tariffs=tariffs or StationTariffs(9.12345678912345, 2456.789123456, 1300.))

    def test_completed_snapshot_is_saved_instead_of_current_ui_values(self):
        c = self.c
        snapshot = self.snapshot()
        c.station_var.set('Ижевская ТЭЦ')
        c.gas_tariff_var.set('999')
        c.output_queue.put(('results', {'snapshot': snapshot}))
        c.output_queue.put(('finished', None))
        c._poll_output()
        self.assertEqual(c.station_repository.get_tariffs('syz_tec'), snapshot.station_tariffs)
        self.assertIsNone(c.station_repository.get_tariffs('izhevsk_tec'))
        self.assertIs(c.last_result, snapshot)
        self.assertEqual(c.excel_button['state'], 'normal')
        fresh = self.controller()
        self.choose(fresh)
        self.assertEqual(float(fresh.gas_tariff_var.get().replace(',', '.')), snapshot.station_tariffs.gas_rub_per_nm3)
        self.assertEqual(float(fresh.electricity_tariff_var.get().replace(',', '.')), snapshot.station_tariffs.electricity_rub_per_mwh)
        self.assertEqual(fresh.electricity_cost_var.get(), '1300')
        before = self.path.read_bytes()
        fresh.gas_tariff_var.set('888')
        self.assertEqual(self.path.read_bytes(), before)  # Editing alone is not a successful run.
        self.choose(fresh, 'СызТЭЦ ГТ-10 другая книга.xlsx')
        self.assertEqual(float(fresh.gas_tariff_var.get().replace(',', '.')), snapshot.station_tariffs.gas_rub_per_nm3)

    def test_cancelled_or_failed_calculation_does_not_save(self):
        c = self.c
        c.gas_tariff_var.set('9,5')
        with patch.object(c, '_ensure_book_mapping', return_value=False):
            c.start_calculation()
        c.output_queue.put(('error', 'synthetic calculation error'))
        c.output_queue.put(('finished', None))
        c._poll_output()
        self.assertFalse(self.path.exists())

    def test_save_failure_keeps_results_and_shows_warning(self):
        c = self.c
        snapshot = self.snapshot()
        with patch.object(c.station_repository, 'save_tariffs', side_effect=OSError('locked')):
            c._show_results({'snapshot': snapshot})
        self.assertIs(c.last_result, snapshot)
        self.assertEqual(c.excel_button['state'], 'normal')
        c.messages.showwarning.assert_called_once()
        self.assertIn('не сохранены', c.messages.showwarning.call_args.args[0])
        self.assertFalse(self.path.exists())

    def test_corrupt_store_is_reported_without_silent_defaults(self):
        self.path.write_text('broken', encoding='utf-8')
        self.choose(self.c)
        self.assertEqual(self.c.gas_tariff_var.get(), '')
        self.assertEqual(self.c.electricity_tariff_var.get(), '')
        self.c.messages.showwarning.assert_called_once()
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'broken')


if __name__ == '__main__':
    unittest.main()
