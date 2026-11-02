import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from unit_conversions import unit_factor, unit_info, UNIT_CATALOG, extract_unit
from data_assembly import suggest_mappings, SensorMapping, validate_mappings


class UnitConversionsTest(unittest.TestCase):
    def test_description_preserves_whole_units_and_prefixes(self):
        for text, expected in [('Скорость т.об/мин','тыс. об/мин'),('Расход нм3/ч','нм³/ч'),
                ('Расход м3/ч','м³/ч'),('Давление кПа','кПа'),('Скорость т.1об/мин',''),
                ('кодгруппа',''),('Давление мм вод. ст.','мм вод. ст.')]:
            with self.subTest(text=text):self.assertEqual(extract_unit(text),expected)

    def test_required_conversions_and_roundtrips(self):
        for source, target, expected in [('мм вод. ст.','Па',9.80665),('кПа','Па',1000.),
                ('мм рт. ст.','Па',133.322368),('бар','МПа',.1),('м3/ч','м3/с',1/3600),
                ('об/мин','Гц',1/60),('т.об/мин','Гц',1000/60),('т/ч','кг/с',1000/3600),
                ('кВт','МВт',.001),('%','о.е.',.01)]:
            with self.subTest(source=source,target=target):
                self.assertAlmostEqual(unit_factor(source,target),expected)
                self.assertAlmostEqual(unit_factor(source,target)*unit_factor(target,source),1.)

    def test_aliases_have_one_meaning(self):
        assigned={}
        for row in UNIT_CATALOG:
            for alias in row['aliases']:
                self.assertEqual(assigned.setdefault(alias,(row['dimension'],row['factor'])),(row['dimension'],row['factor']))
                self.assertEqual(unit_info(alias),row)
        self.assertEqual(unit_factor('М3/Ч','м³/с'),1/3600)
        self.assertEqual(unit_factor('°С','°C'),1.)

    def test_incompatible_and_affine_units_cannot_use_a_multiplier(self):
        for source,target in [('кПа','кг/с'),('нм3/ч','м3/ч'),('кг/с','м3/с'),('°C','K')]:
            with self.subTest(source=source,target=target),self.assertRaises(ValueError):unit_factor(source,target)

    def test_destination_and_factor_are_checked_on_import(self):
        headers={'AN':'n, Гц'}
        correct=SensorMapping('SPEED','AN',1/60,source_unit='об/мин',target_unit='Гц')
        validate_mappings([correct],['SPEED'],target_headers=headers)
        with self.assertRaisesRegex(ValueError,'Коэффициент'):
            validate_mappings([SensorMapping('SPEED','AN',1.,source_unit='об/мин',target_unit='Гц')],['SPEED'],target_headers=headers)
        with self.assertRaisesRegex(ValueError,'Единицы назначения'):
            validate_mappings([SensorMapping('SPEED','AN',1.,source_unit='об/мин',target_unit='об/мин')],['SPEED'],target_headers=headers)

    def test_power_factor_channel_is_not_forced_into_a_placeholder(self):
        result=suggest_mappings(['10MKA01FE006'],'Ижевская ГТ-1.xlsx',station_id='izhevsk_tec',unit='1',target_headers={'AM':'cosφ'})
        self.assertEqual(result[0].target,'')
        self.assertEqual(result[0].status,'mapped')
        validate_mappings([SensorMapping('10MKA01FE006','AM',source_unit='о.е.',target_unit='о.е.')],
                          ['10MKA01FE006'],target_headers={'AM':'cosφ'})
