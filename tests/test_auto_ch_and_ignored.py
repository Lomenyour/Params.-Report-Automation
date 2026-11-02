import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from gas_composition import calculate_ch, CH_METHOD
from gas_passport import GasPassport, GasPassportHistory, gas_values, read_book_passport
from gas_passport_ui import passport_from_fields, passport_fields
from data_assembly import SensorMapping, assemble_sensor_data, save_mappings, load_saved_mappings
from result_export import DataSheetValues, save_result_workbook


def values():
    return {'density_kg_per_nm3':'.7','q_lower_mj_per_nm3':'35','component:Methane':'1'}


class AutomaticCHTest(unittest.TestCase):
    def test_chemical_formulas_and_inert_components(self):
        self.assertAlmostEqual(calculate_ch({'Methane':1}),12.011/(4*1.008))
        self.assertAlmostEqual(calculate_ch({'Ethane':1}),2*12.011/(6*1.008))
        self.assertAlmostEqual(calculate_ch({'n-Heptane':1}),7*12.011/(16*1.008))
        self.assertAlmostEqual(calculate_ch({'IsoButane':1}),calculate_ch({'n-Butane':1}))
        mixture=calculate_ch({'Methane':.9,'Ethane':.1})
        self.assertAlmostEqual(mixture,12.011*1.1/(1.008*4.2))
        self.assertAlmostEqual(mixture,calculate_ch({'Methane':.45,'Ethane':.05,'CarbonDioxide':.2,'Nitrogen':.1,'Oxygen':.1,'Helium':.1}))

    def test_hydrogen_and_invalid_composition(self):
        self.assertEqual(calculate_ch({'Hydrogen':1}),0.)
        self.assertLess(calculate_ch({'Methane':.5,'Hydrogen':.5}),calculate_ch({'Methane':1}))
        for composition in ({},{'Nitrogen':1},{'Unknown':.1,'Methane':.9},{'Methane':96},{'Methane':float('nan')}):
            with self.subTest(composition=composition),self.assertRaises(ValueError):calculate_ch(composition)

    def test_editor_computes_ratio_and_does_not_trust_posted_value(self):
        fields={**values(),'carbon_hydrogen_ratio':'999'};before=copy.deepcopy(fields)
        result=passport_from_fields(fields,'syz_tec','10')
        self.assertAlmostEqual(result.carbon_hydrogen_ratio,12.011/(4*1.008))
        self.assertEqual(result.carbon_hydrogen_ratio_method,CH_METHOD)
        self.assertEqual(fields,before)
        self.assertTrue(next(field for field in passport_fields(result) if field['key']=='carbon_hydrogen_ratio')['computed'])
        self.assertEqual(GasPassport.from_dict(result.to_dict()),result)
        with self.assertRaisesRegex(ValueError,'не совпадает'):
            GasPassport.from_dict({**result.to_dict(),'carbon_hydrogen_ratio':999})

    def test_legacy_remains_reproducible_until_explicit_save(self):
        legacy=GasPassport.from_dict({'station_id':'syz_tec','unit':'10','density_kg_per_nm3':.7,
            'q_lower_mj_per_nm3':35,'carbon_hydrogen_ratio':3.1,'components':{'Methane':1}})
        self.assertEqual(legacy.carbon_hydrogen_ratio,3.1)
        self.assertEqual(legacy.carbon_hydrogen_ratio_method,'')
        with self.assertRaisesRegex(ValueError,'молярные доли'):
            passport_from_fields({'density_kg_per_nm3':'.7','q_lower_mj_per_nm3':'35'},'syz_tec','10')

    def test_history_uses_each_composition_and_survives_excel(self):
        first=passport_from_fields(values(),'syz_tec','10').to_dict()
        second=passport_from_fields({'density_kg_per_nm3':'.7','q_lower_mj_per_nm3':'35','component:Ethane':'1'},'syz_tec','10').to_dict()
        first.update(valid_from='2026-01-01',valid_until='2026-02-01')
        second.update(valid_from='2026-02-01',valid_until='2026-03-01')
        history=GasPassportHistory.from_dict(dict(station_id='syz_tec',unit='10',entries=[first,second]))
        result=gas_values(history,pd.to_datetime(['2026-01-31 23:30','2026-02-01 00:00']))['carbon_hydrogen_ratio']
        np.testing.assert_allclose(result,[12.011/(4*1.008),2*12.011/(6*1.008)])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.xlsx'
            save_result_workbook(DataSheetValues(pd.DataFrame([[None,'Дата']]),0),[],path,gas_passport=history)
            self.assertEqual(read_book_passport(path,'syz_tec','10').to_dict(),history.to_dict())


class IgnoredChannelTest(unittest.TestCase):
    def test_ignored_channel_is_not_imported_or_exported(self):
        dates=pd.to_datetime(['2026-01-01 00:00','2026-01-01 00:30'])
        base=pd.DataFrame({'B':dates[:1],'C':[100000.],'F':[20.],'AM':[.9]},index=dates[:1]).astype(object)
        raw=pd.DataFrame({'TEMP':[25.,26.],'PF':[6362.9,'X']},index=dates)
        before=raw.copy(deep=True)
        headers={'B':'Дата','C':'Pатм, Па','F':'Токр, °C','AM':'cosφ'}
        maps=[SensorMapping('TEMP','F'),SensorMapping('PF','',status='ignored')]
        with patch('data_assembly._read_template',return_value=(base,headers,None)),patch('data_assembly._read_sensor_sheet',return_value=raw):
            result=assemble_sensor_data('СызТЭЦ ГТ-10.xlsx','source.xlsx','Sheet1',maps,station_id='syz_tec',unit='10')
        self.assertEqual(result.values.F.tolist(),[25.,26.])
        self.assertEqual(result.values.AM.iloc[0],.9)
        self.assertTrue(pd.isna(result.values.AM.iloc[1]))
        self.assertFalse(any('PF' in str(header) for header in result.headers.values()))
        self.assertEqual(result.source_diagnostics['ignored_channels'],['PF'])
        pd.testing.assert_frame_equal(raw,before)
        with tempfile.TemporaryDirectory() as folder:
            from openpyxl import load_workbook
            path=Path(folder)/'ignored.xlsx';save_result_workbook(result,[],path)
            workbook=load_workbook(path,read_only=True,data_only=True)
            rows=list(workbook['Данные'].values);workbook.close()
            self.assertFalse(any('PF' in str(header) for header in rows[0]))
            column=rows[0].index('cosφ')
            self.assertEqual(rows[1][column],.9);self.assertIsNone(rows[2][column])

    def test_ignored_choice_is_saved_and_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder,patch('data_assembly._mapping_profile_path',return_value=Path(folder)/'map.json'):
            save_mappings('СызТЭЦ ГТ-10.xlsx',['PF'],[SensorMapping('PF','',status='ignored')],station_id='syz_tec',unit='10')
            loaded=load_saved_mappings('СызТЭЦ ГТ-10.xlsx',['PF'],station_id='syz_tec',unit='10',target_headers={'AM':'cosφ'})
            self.assertEqual(loaded[0].status,'ignored')
            save_mappings('СызТЭЦ ГТ-10.xlsx',['PF'],[SensorMapping('PF','AM')],station_id='syz_tec',unit='10')
            self.assertEqual(load_saved_mappings('СызТЭЦ ГТ-10.xlsx',['PF'],station_id='syz_tec',unit='10')[0].status,'mapped')
