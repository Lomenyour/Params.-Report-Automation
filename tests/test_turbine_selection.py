"""Справочник оборудования, буквенные номера и единая ручная идентичность."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
from data_assembly import SensorMapping, suggest_mappings, save_mappings, load_saved_mappings, read_calculation_profile
from gas_passport import GasPassport
from correction_profiles import CorrectionProfile, FIELDS
from station_profiles import get_station_repository, unit_number


class EquipmentCatalogTest(unittest.TestCase):
    def setUp(self):
        self.repo = get_station_repository()

    def test_complete_catalog_and_confirmed_models(self):
        self.assertEqual(len(self.repo.companies), 9)
        self.assertEqual(len(self.repo.list_stations()), 33)
        self.assertEqual(sum(len(self.repo.list_turbines(s.id)) for s in self.repo.list_stations()), 57)
        self.assertEqual(self.repo.get_turbine('syz_tec', '10').model, 'PG6111FA')
        self.assertEqual(self.repo.get_turbine('mos_tec_26', '1').model, 'GT-26B')
        self.assertIsNone(self.repo.get_tariffs('mos_tec_26'))
        self.assertFalse(self.repo.get_turbine('mos_tec_26','1').calculation_method)

    def test_station_names_and_string_unit_numbers(self):
        for name, number in [('ГТ-10','10'),('GT_11','11'),('ГТУ-11Б','11Б'),('gtu11','11'),('ГТУ-11В','11В')]:
            self.assertEqual(unit_number(name+'.xlsx'), number)
        self.assertIsNone(unit_number('ГТУ-10 и ГТУ-11.xlsx'))
        self.assertEqual(self.repo.detect_station('Пермская ТЭЦ-9 ГТУ-1.xlsx').id, 'perm_tec_9')
        self.assertEqual(self.repo.detect_turbine('ТЭЦ-26 ГТУ-1 GT-26B.xlsx','mos_tec_26').number,'1')
        self.assertEqual(self.repo.detect_turbine('ТЭЦ-21 ГТУ-11Б.xlsx','mos_tec_21').number,'11Б')
        self.assertIsNone(self.repo.detect_turbine('ГТУ-11.xlsx','mos_tec_21'))

    def test_manual_unit_controls_sensor_suggestions_and_saved_mapping_keys(self):
        headers=['G1.CSGV','G2.CSGV']
        result=suggest_mappings(headers, 'СызТЭЦ ГТУ-11.xlsx',station_id='syz_tec',unit='10')
        self.assertEqual([r.target for r in result],['V',''])
        with tempfile.TemporaryDirectory() as folder, patch('data_assembly._mapping_profile_path',return_value=Path(folder)/'map.json'):
            first=[SensorMapping('G1.CSGV','V')]
            save_mappings('без номера.xlsx',headers,first,station_id='syz_tec',unit='10')
            self.assertEqual(load_saved_mappings('СызТЭЦ ГТ-11.xlsx',headers,station_id='syz_tec',unit='10'), first)
            self.assertIsNone(load_saved_mappings('без номера.xlsx',headers,station_id='syz_tec',unit='11'))

    def test_manual_profile_identity_overrides_filename_and_checks_gas(self):
        profile=CorrectionProfile('syz_tec','10',tuple((field.key,1.) for field in FIELDS))
        passport=GasPassport('syz_tec','10',.7,34.13,3.)
        result=read_calculation_profile('СызТЭЦ ГТУ-11.xlsx',station_id='syz_tec',unit='10',
            correction_profile=profile,gas_passport=passport)
        self.assertEqual(result['gas_density'],.7)
        with self.assertRaisesRegex(ValueError,'Паспорт газа'):
            read_calculation_profile('СызТЭЦ ГТУ-11.xlsx',station_id='syz_tec',unit='10',
                correction_profile=profile,gas_passport=GasPassport('syz_tec','11',.7,34.13,3.))

    def test_passport_string_identifier_does_not_collapse_letters(self):
        for unit in ('11Б','11В'):
            passport=GasPassport.from_dict({'station_id':'mos_tec_21','unit':unit,
                'density_kg_per_nm3':.7,'q_lower_mj_per_nm3':34.,'carbon_hydrogen_ratio':3.})
            self.assertEqual(passport.unit,unit)


if __name__ == '__main__':
    unittest.main()
