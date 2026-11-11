import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from station_profiles import JsonStationRepository, catalog_path, station_sort_key, unit_number
from gas_passport import GasPassport, load_passport, save_passport


class StationCreationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'user_stations.json'
        self.repository=JsonStationRepository(catalog_path(),catalog_store=self.path)
        self.base_hash=hashlib.sha256(catalog_path().read_bytes()).hexdigest()

    def create(self,name='Тестовая Казанская ТЭЦ-1',**kwargs):
        return self.repository.create_station(name,'11б','Тестовая модель',
            filename_aliases=['ТестКазТЭЦ-1'],name_genitive='Тестовой Казанской ТЭЦ-1',**kwargs)

    def test_sort_is_alphabetical_and_natural_for_numbers(self):
        names=['ТЭЦ-12','Ярославская ТЭЦ','Академическая ТЭЦ','ТЭЦ-2','ТЭЦ-9']
        self.assertEqual(sorted(names,key=station_sort_key),
            ['Академическая ТЭЦ','ТЭЦ-2','ТЭЦ-9','ТЭЦ-12','Ярославская ТЭЦ'])
        actual=[row.name for row in self.repository.list_stations()]
        self.assertEqual(actual,sorted(actual,key=station_sort_key))
        self.assertEqual(station_sort_key('Орёл'),station_sort_key('Орел'))

    def test_creation_selectable_and_survives_reload_without_base_change(self):
        station,turbine=self.create()
        self.assertEqual(turbine.number,'11Б')
        self.assertEqual(station.name_genitive,'Тестовой Казанской ТЭЦ-1')
        self.assertEqual(self.repository.list_turbines(station.id),(turbine,))
        self.assertEqual(self.repository.detect_station('ТестКазТЭЦ-1.xlsb'),station)
        self.assertIsNone(unit_number('КазТЭЦ-1.xlsb'))
        self.assertIsNone(self.repository.get_tariffs(station.id))
        self.assertEqual(self.repository.get_channels(station.id),())
        reloaded=JsonStationRepository(catalog_path(),catalog_store=self.path)
        self.assertEqual(reloaded.get_station(station.id),station)
        self.assertEqual(reloaded.get_turbine(station.id,'11Б'),turbine)
        self.assertEqual(hashlib.sha256(catalog_path().read_bytes()).hexdigest(),self.base_hash)

    def test_exact_names_and_known_aliases_rejected_without_fuzzy_matching(self):
        for name in ('СызТЭЦ',' СЫЗ-ТЭЦ ','Сызранская ТЭЦ'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'уже есть'):
                self.repository.create_station(name,'1','Тест')
        # Similarity search is intentionally absent; only exact normalized keys.
        station,_=self.repository.create_station('Тестовая Кировская ТЭЦ-3','1','Тест')
        self.assertEqual(station.name,'Тестовая Кировская ТЭЦ-3')

    def test_invalid_fields_do_not_change_persisted_or_live_catalogue(self):
        self.create()
        before=self.path.read_bytes()
        count=len(self.repository.list_stations())
        for name,number,model,extra in [('', '1','Тест',{}),('Новая','1.5','Тест',{}),
            ('Новая','1','',{}),('Новая','1','Тест',{'company_id':'missing'}),
            ('Новая','1','Тест',{'filename_aliases':['СызТЭЦ']})]:
            with self.subTest(name=name,number=number,model=model),self.assertRaises(ValueError):
                self.repository.create_station(name,number,model,**extra)
            self.assertEqual(self.path.read_bytes(),before)
            self.assertEqual(len(self.repository.list_stations()),count)

    def test_write_failure_preserves_existing_file_and_live_selection(self):
        self.create()
        before=self.path.read_bytes()
        with patch('json_store.os.replace',side_effect=OSError('test failure')):
            with self.assertRaises(OSError):
                self.repository.create_station('Другая тестовая ТЭЦ','1','Тест')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(self.repository.detect_station('Другая тестовая ТЭЦ.xlsx'))

    def test_stale_repository_preserves_other_saved_additions(self):
        second=JsonStationRepository(catalog_path(),catalog_store=self.path)
        first,_=self.create()
        last,_=second.create_station('Другая тестовая ТЭЦ','1','Тест')
        final=JsonStationRepository(catalog_path(),catalog_store=self.path)
        self.assertEqual(final.get_station(first.id),first)
        self.assertEqual(final.get_station(last.id),last)

    def test_malformed_user_file_is_rejected_without_rewrite(self):
        for data in ({'schema_version':5,'stations':[],'turbines':[]},
                     {'schema_version':1,'stations':[{'id':'x','name':None,'filename_aliases':[]}],'turbines':[]}):
            self.path.write_text(json.dumps(data),encoding='utf-8')
            before=self.path.read_bytes()
            with self.assertRaises(ValueError):
                JsonStationRepository(catalog_path(),catalog_store=self.path)
            self.assertEqual(self.path.read_bytes(),before)

    def test_new_pair_has_its_own_empty_then_saved_gas_passport(self):
        station,turbine=self.create()
        passport_file=Path(self.folder.name)/'gas_passport_history.json'
        with patch('gas_passport.passport_path',return_value=passport_file):
            self.assertIsNone(load_passport(station.id,turbine.number))
            passport=GasPassport.from_dict(dict(station_id=station.id,unit=turbine.number,
                density_kg_per_nm3=.7,q_lower_mj_per_nm3=35.,carbon_hydrogen_ratio=3.,components={'CH4':1.}))
            saved=save_passport(passport)
            self.assertEqual(load_passport(station.id,turbine.number),saved)
            self.assertIsNone(load_passport('syz_tec','11Б'))


if __name__=='__main__':unittest.main()
