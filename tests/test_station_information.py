"""Station reference joins and private contact imports, without calculation changes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from station_information import read_information
from station_profiles import JsonStationRepository, catalog_path


class StationInformationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'information.json'
        self.repository = JsonStationRepository(catalog_path(), information_store=self.path)

    def test_join_catalog_station_company_turbines_and_private_names_after_restart(self):
        before = catalog_path().read_bytes()
        self.repository.save_station_contacts({'syz_tec': ['Иванов Иван Иванович', 'Петров П. П.']})
        fresh = JsonStationRepository(catalog_path(), information_store=self.path)
        info = fresh.get_station_information('syz_tec')
        self.assertEqual(info.station, fresh.get_station('syz_tec'))
        self.assertEqual(info.company_name, fresh.companies[info.station.company_id])
        self.assertEqual(info.turbines, fresh.list_turbines('syz_tec'))
        self.assertEqual({t.number for t in info.turbines}, {'10', '11'})
        self.assertEqual(info.contact_names, ('Иванов Иван Иванович', 'Петров П. П.'))
        self.assertEqual(fresh.get_station_information('izhevsk_tec').contact_names, ())
        self.assertEqual(catalog_path().read_bytes(), before)
        self.assertEqual(JsonStationRepository(catalog_path()).get_station_information('syz_tec').contact_names, ())

    def test_import_preserves_other_names_deduplicates_and_keeps_unmatched_separate(self):
        self.repository.save_station_contacts({'syz_tec': ['Иванов Иван Иванович']})
        self.repository.save_station_contacts(
            {'syz_tec': ['Иванов Иван Иванович', ' Петров Петр '], 'izhevsk_tec': ['Сидоров С. И.']},
            unassigned={'Новая станция': ['Петров Петр']}, source={'sheet': 'Лист2'})
        data = read_information(self.path)
        self.assertEqual(data['contacts']['syz_tec'], ['Иванов Иван Иванович', 'Петров Петр'])
        self.assertEqual(data['contacts']['izhevsk_tec'], ['Сидоров С. И.'])
        self.assertEqual(data['unassigned'], {'Новая станция': ['Петров Петр']})
        self.assertEqual(data['source'], {'sheet': 'Лист2'})
        self.assertTrue(self.path.with_suffix('.json.bak').is_file())

    def test_bad_or_unknown_records_do_not_partially_write(self):
        self.repository.save_station_contacts({'syz_tec': ['Иванов Иван Иванович']})
        before = self.path.read_bytes()
        invalid = ['person@example.org', '+7 (000) 000-00-00', 'Иванов Иван 123', 'Иван', None]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repository.save_station_contacts({'izhevsk_tec': ['Петров Петр'], 'syz_tec': [value]})
            self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.repository.save_station_contacts({'syz_tec': ['Петров Петр'], 'unknown': ['Петров Петр']})
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_atomic_write_and_corrupt_file_preserve_previous_bytes(self):
        self.repository.save_station_contacts({'syz_tec': ['Иванов Иван Иванович']})
        before = self.path.read_bytes()
        with patch('json_store.os.replace', side_effect=OSError('locked')), self.assertRaises(OSError):
            self.repository.save_station_contacts({'syz_tec': ['Петров Петр']})
        self.assertEqual(self.path.read_bytes(), before)
        for content in ('broken', '{"schema_version":2,"contacts":{},"unassigned":{}}',
                        json.dumps({'schema_version': 1, 'contacts': {'syz_tec': ['Иван']}, 'unassigned': {}})):
            self.path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                self.repository.save_station_contacts({'syz_tec': ['Петров Петр']})
            self.assertEqual(self.path.read_text(encoding='utf-8'), content)


if __name__ == '__main__':
    unittest.main()
