import sys
from pathlib import Path
import unittest
import json
import tempfile
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from unit_conversions import unit_factor, unit_info, UNIT_CATALOG, extract_unit, unit_conversion, convert_units
from data_assembly import (suggest_mappings, SensorMapping, validate_mappings,
                           _convert_sensor, assemble_sensor_data, save_mappings, load_saved_mappings)


class UnitConversionsTest(unittest.TestCase):
    def test_description_preserves_whole_units_and_prefixes(self):
        for text, expected in [('Скорость т.об/мин','тыс. об/мин'),('Расход нм3/ч','нм³/ч'),
                ('Расход м3/ч','м³/ч'),('Давление кПа','кПа'),('Скорость т.1об/мин',''),
                ('кодгруппа',''),('Давление мм вод. ст.','мм вод. ст.'),('Температура, K','K'),
                ('Температура, °F','°F'),('Температура [K]','K'),('TAG_K',''),
                ('Давление inH2O','дюйм вод. ст. (условн.)'),('Давление in. w.c.','дюйм вод. ст. (условн.)'),
                ('Давление inH2O (60 °F)','дюйм вод. ст. (60 °F)'),('Давление inH2O @ 4 °C','дюйм вод. ст. (4 °C)')]:
            with self.subTest(text=text):self.assertEqual(extract_unit(text),expected)

    def test_required_conversions_and_roundtrips(self):
        for source, target, expected in [('мм вод. ст.','Па',9.80665),('кПа','Па',1000.),
                ('мм рт. ст.','Па',133.322368),('бар','МПа',.1),('м3/ч','м3/с',1/3600),
                ('об/мин','Гц',1/60),('т.об/мин','Гц',1000/60),('т/ч','кг/с',1000/3600),
                ('кВт','МВт',.001),('%','о.е.',.01),('inH2O','Па',249.08891),
                ('inH2O (4 °C)','Па',249.082),('inH2O (60 °F)','Па',248.84),('inHg','Па',3386.389)]:
            with self.subTest(source=source,target=target):
                self.assertAlmostEqual(unit_factor(source,target),expected)
                self.assertAlmostEqual(unit_factor(source,target)*unit_factor(target,source),1.)

    def test_aliases_have_one_meaning(self):
        assigned={}
        for row in UNIT_CATALOG:
            for alias in row['aliases']:
                meaning=(row['dimension'],row['factor'],row['offset'])
                self.assertEqual(assigned.setdefault(alias,meaning),meaning)
                self.assertEqual(unit_info(alias),row)
        self.assertEqual(unit_factor('М3/Ч','м³/с'),1/3600)
        self.assertEqual(unit_factor('°С','°C'),1.)

    def test_all_temperature_directions_against_reference_points(self):
        points={'°C':np.array([-40.,0.,100.]),'K':np.array([233.15,273.15,373.15]),
                '°F':np.array([-40.,32.,212.])}
        for source,values in points.items():
            for target,expected in points.items():
                with self.subTest(source=source,target=target):
                    np.testing.assert_allclose(convert_units(values,source,target),expected,atol=1e-12)
                    self.assertAlmostEqual(convert_units(float(values[1]),source,target),expected[1])
                    multiplier,offset=unit_conversion(source,target)
                    np.testing.assert_allclose(values*multiplier+offset,expected,atol=1e-12)
        self.assertAlmostEqual(unit_conversion('K','°C')[1],-273.15)

    def test_temperature_offset_keeps_missing_and_invalid_raw_readings(self):
        source=pd.Series(['32',' 212,0 ',None,'BAD',-40.])
        before=source.copy(deep=True)
        actual,invalid=_convert_sensor(source,*unit_conversion('°F','°C'))
        np.testing.assert_allclose(actual.iloc[[0,1,4]].astype(float),[0.,100.,-40.],atol=1e-12)
        self.assertTrue(pd.isna(actual.iloc[2]));self.assertEqual(actual.iloc[3],'BAD')
        self.assertEqual(invalid,1);pd.testing.assert_series_equal(source,before)

    def test_import_applies_offset_once_preserving_earlier_history(self):
        dates=pd.date_range('2026-01-01',periods=4,freq='30min')
        base=pd.DataFrame({'B':dates[:2],'F':[10.,20.]},index=dates[:2]).astype(object)
        raw=pd.DataFrame({'TEMP':[273.15,283.15,'BAD']},index=dates[1:])
        mapping=SensorMapping('TEMP','F',source_unit='K',target_unit='°C',offset=-273.15)
        with patch('data_assembly._read_template',return_value=(base,{'B':'Дата','F':'Токр, °C'},None)), \
                patch('data_assembly._read_sensor_sheet',return_value=raw):
            result=assemble_sensor_data('СызТЭЦ ГТ-10.xlsx','raw.xlsx','Sheet1',[mapping],station_id='syz_tec',unit='10')
        np.testing.assert_allclose(result.values.F.iloc[:3].astype(float),[10.,0.,10.],atol=1e-12)
        self.assertEqual(result.values.F.iloc[3],'BAD')
        self.assertEqual(len(result.values),4)
        self.assertEqual(base.F.tolist(),[10.,20.])

    def test_offset_and_destination_are_validated_even_when_multiplier_is_one(self):
        correct=SensorMapping('TEMP','F',source_unit='K',target_unit='°C',offset=-273.15)
        validate_mappings([correct],['TEMP'],target_headers={'F':'Токр, °C'})
        with self.assertRaisesRegex(ValueError,'Смещение'):
            validate_mappings([replace(correct,offset=0.)],['TEMP'],target_headers={'F':'Токр, °C'})
        with self.assertRaisesRegex(ValueError,'Единицы назначения'):
            validate_mappings([replace(correct,offset=0.,target_unit='K')],['TEMP'],target_headers={'F':'Токр, °C'})
        with self.assertRaisesRegex(ValueError,'укажите'):
            validate_mappings([replace(correct,source_unit='')],['TEMP'],target_headers={'F':'Токр, °C'})

    def test_offset_persists_and_legacy_mapping_defaults_to_zero(self):
        mapping=SensorMapping('TEMP','F',source_unit='K',target_unit='°C',offset=-273.15)
        with tempfile.TemporaryDirectory() as folder,patch('data_assembly._mapping_profile_path',return_value=Path(folder)/'map.json'):
            save_mappings('ГТ-10.xlsx',['TEMP'],[mapping],station_id='syz_tec',unit='10')
            loaded=load_saved_mappings('ГТ-10.xlsx',['TEMP'],station_id='syz_tec',unit='10')
            self.assertEqual(loaded,[mapping])
            # Every saved version without the new field remains readable.
            path=Path(folder)/'map.json';data=json.loads(path.read_text(encoding='utf-8'))
            def legacy(value):
                if isinstance(value,dict):
                    value.pop('offset',None)
                    for child in value.values():legacy(child)
                elif isinstance(value,list):
                    for child in value:legacy(child)
            legacy(data);path.write_text(json.dumps(data),encoding='utf-8')
            self.assertEqual(load_saved_mappings('ГТ-10.xlsx',['TEMP'],station_id='syz_tec',unit='10')[0].offset,0.)

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
