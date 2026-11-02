"""Confirmation storage, exact variants, half-hour readers and date-dependent gas inputs."""
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
from gas_passport import GasPassport, GasPassportHistory, gas_values, load_passport, save_passport, read_book_passport
from gas_passport_ui import history_from_rows
from data_assembly import SensorMapping, load_saved_mappings, save_mappings, recalculate_gas_columns
from sensor_mapping_store import load_store
from source_readers import _horizontal, read_sensor_sheet
from source_variants import match_variant
from result_export import DataSheetValues, save_result_workbook
from data_loader import load_source_data, prepare_vna_data


def gas(density=.7, q=35., start='', end=''):
    return dict(station_id='syz_tec', unit='10', density_kg_per_nm3=density,
                q_lower_mj_per_nm3=q, carbon_hydrogen_ratio=3., valid_from=start, valid_until=end)


def history():
    return GasPassportHistory.from_dict(dict(station_id='syz_tec',unit='10',entries=[
        gas(start='2026-01-01',end='2026-02-01'), gas(.75,36.,'2026-02-01','2026-03-01')]))


class GasHistoryTests(unittest.TestCase):
    def test_boundary_and_missing_coverage(self):
        values=gas_values(history(),pd.Series(['2026-01-31 23:30','2026-02-01 00:00',None]))
        np.testing.assert_allclose(values['density_kg_per_nm3'][:2],[.7,.75])
        np.testing.assert_allclose(values['q_lower_mj_per_nm3'][:2],[35.,36.])
        self.assertTrue(np.isnan(values['q_lower_mj_per_nm3'][2]))
        with self.assertRaisesRegex(ValueError,'Нет паспорта'):
            gas_values(history(),pd.Series(['2026-03-01']))

    def test_overlap_and_unbounded_multiple_are_rejected(self):
        for entries in ([gas(),gas()], [gas(start='2026-01-01',end='2026-02-02'),gas(start='2026-02-01',end='2026-03-01')]):
            with self.assertRaises(ValueError):
                GasPassportHistory.from_dict(dict(station_id='syz_tec',unit='10',entries=entries))

    def test_legacy_load_does_not_rewrite_file_and_history_is_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'gas.json'
            path.write_text(json.dumps(dict(schema_version=1,passports={'syz_tec|10':gas()})),encoding='utf-8')
            original=path.read_bytes()
            with patch('gas_passport.passport_path',return_value=path):
                self.assertIsInstance(load_passport('syz_tec','10'),GasPassport)
                self.assertEqual(path.read_bytes(),original)
                save_passport(history())
                self.assertEqual(len(load_passport('syz_tec','10').entries),2)
                self.assertIsNone(load_passport('syz_tec','11'))
            self.assertEqual(path.with_suffix('.json.bak').read_bytes(),original)

    def test_recalculation_uses_row_density_and_volumetric_heat(self):
        frame=pd.DataFrame({key:[1.,1.] for key in ('D','H','O','T','AE','AI','AN','AS')})
        frame['AO']=[100.,100.];frame['B']=pd.to_datetime(['2026-01-31 23:30','2026-02-01 00:00'])
        profile={'gas_history':history().to_dict(),'gas_density':.7,
                 **{f'fuel_properties.{key}':0. for key in ('q2','q1','q0','b2','b1')},
                 'fuel_properties.b0':1.,'fuel_reference.n1':.05,'fuel_reference.n0':100.}
        recalculate_gas_columns(frame,profile)
        np.testing.assert_allclose(frame['AK'],[35./.7,36./.75])
        np.testing.assert_allclose(frame['AT'],[3600./.7,3600./.75])
        np.testing.assert_allclose(frame['AX'],[(105*3600/.7)/100,(105*3600/.75)/100])
        np.testing.assert_allclose(frame['AS'],[1.,1.])

    def test_history_export_can_be_reloaded_without_user_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.xlsx'
            data=DataSheetValues(pd.DataFrame([[None,'Дата'],[0,pd.Timestamp('2026-01-01')]]),0)
            save_result_workbook(data,[],path,gas_passport=history())
            restored=read_book_passport(path,'syz_tec','10')
            self.assertIsInstance(restored,GasPassportHistory)
            self.assertEqual(restored.to_dict(),history().to_dict())
            from correction_sheet import read_correction_sheet
            second=Path(folder)/'second.xlsx'
            save_result_workbook(data,[],second,correction_sheet=read_correction_sheet(path),gas_passport=history())
            self.assertEqual(read_book_passport(second,'syz_tec','10').to_dict(),history().to_dict())

    def test_editor_dates_are_not_ignored(self):
        values={key:str(value) for key,value in gas().items()}
        result=history_from_rows([dict(values=values,valid_from='2026-01-01',valid_until='2026-02-01')],'syz_tec','10')
        with self.assertRaises(ValueError):gas_values(result,['2026-02-01'])

    def test_ambiguous_passport_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'ГГГГ-ММ-ДД'):
            GasPassport.from_dict({**gas(), 'valid_from':'01/02/2026', 'valid_until':'03/04/2026'})


class MappingHistoryTests(unittest.TestCase):
    def test_station_assignments_precede_legacy_header_aliases(self):
        from data_assembly import suggest_mappings
        result=suggest_mappings(['G1.APCS_c','G1.TR96TF2_c','G1.TR96TF3_c'],
            'СызТЭЦ ГТ-10.xlsx',station_id='syz_tec',unit='10',
            target_headers={'J':'ВЛО, Па','K':'ФГО+ФТО, Па','L':'Δpнк, Па'})
        self.assertEqual([item.target for item in result],['L','J','K'])

    def test_new_tag_keeps_known_assignment_and_old_set(self):
        with tempfile.TemporaryDirectory() as folder,patch('data_assembly._mapping_profile_path',return_value=Path(folder)/'map.json'):
            first=[SensorMapping('A','P'),SensorMapping('OLD','V')]
            save_mappings('ГТ-10.xlsx',['date','time','A','OLD'],first,station_id='syz_tec',unit='10')
            actual=load_saved_mappings('ГТ-10.xlsx',['NEW','A','date','time'],station_id='syz_tec',unit='10')
            self.assertEqual([(item.source,item.target) for item in actual],[('NEW',''),('A','P')])
            second=[SensorMapping('A','P'),SensorMapping('NEW','V')]
            save_mappings('ГТ-10.xlsx',['date','time','A','NEW'],second,station_id='syz_tec',unit='10')
            self.assertEqual(load_saved_mappings('ГТ-10.xlsx',['time','OLD','A','date'],station_id='syz_tec',unit='10'),[first[1],first[0]])
            self.assertIsNone(load_saved_mappings('ГТ-11.xlsx',['A','NEW'],station_id='syz_tec',unit='11'))

    def test_corrupt_json_and_failed_replace_preserve_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'map.json'
            with patch('data_assembly._mapping_profile_path',return_value=path):
                path.write_text('broken',encoding='utf-8')
                with self.assertRaises(ValueError):save_mappings('ГТ-10.xlsx',['A'],[SensorMapping('A','P')],station_id='syz_tec')
                self.assertEqual(path.read_text(),'broken')
                path.unlink()
                save_mappings('ГТ-10.xlsx',['A'],[SensorMapping('A','P')],station_id='syz_tec')
                original=path.read_bytes()
                with patch('json_store.os.replace',side_effect=OSError('locked')),self.assertRaises(OSError):
                    save_mappings('ГТ-10.xlsx',['A'],[SensorMapping('A','V')],station_id='syz_tec')
                self.assertEqual(path.read_bytes(),original)

    def test_variant_requires_exact_set_and_company(self):
        from source_variants import variants_path
        entry=next(item for item in json.loads(variants_path().read_text(encoding='utf-8'))['variants'] if item['id']=='reference_2')
        tags=[item['tag'] for item in entry['assignments']]
        self.assertEqual(match_variant(list(reversed(tags))+['date','time'],'t_plus')['id'],'reference_2')
        self.assertIsNone(match_variant(tags+['OTHER'],'t_plus'))
        self.assertIsNone(match_variant(tags,'mosenergo'))

    def test_destination_pressure_unit_must_match_workbook(self):
        from data_assembly import validate_mappings
        with self.assertRaisesRegex(ValueError,'Единицы назначения'):
            validate_mappings([SensorMapping('A','C',source_unit='кПа',target_unit='Па')],['A'],target_headers={'C':'Pатм, кПа'})


class ReaderTests(unittest.TestCase):
    def test_rotation_and_power_need_explicit_units(self):
        from parameter_mapping import parameter_for_header
        self.assertEqual(parameter_for_header('n, Гц'), 'rpm')
        self.assertEqual(parameter_for_header('n, об/мин'), 'rpm')
        self.assertEqual(parameter_for_header('N, МВт'), 'power')
        self.assertEqual(parameter_for_header('N'), '')

    def test_foreign_layout_cannot_be_recalculated_as_syzran(self):
        from data_assembly import AssembledData, calculate_data_columns
        data=AssembledData(pd.DataFrame({'Y':[95.]}),{'Y':'ВНА'},0,0,{},[])
        with self.assertRaisesRegex(ValueError,'Чужая методика'):
            calculate_data_columns(data,{})

    def test_csv_metadata_and_conflicting_units(self):
        def metadata(unit):
            row=['']*19
            row[1],row[3],row[7],row[18]='1','TAG_A','Давление',unit
            return row
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.csv'
            def save(rows):
                with path.open('w',encoding='utf-8-sig',newline='') as handle:
                    csv.writer(handle,delimiter=';').writerows(rows)
            rows=[metadata('кПа'),['','Время','Тег1'],['','2026.01.01 00:00:00,000','100,5'],
                  ['','2026.01.01 00:10:00,000','101,5'],['','2026.01.01 00:30:00,000','X']]
            save(rows)
            result=read_sensor_sheet(path,'CSV')
            self.assertEqual(result['TAG_A'].tolist(),['100,5','X'])
            self.assertEqual(result.attrs['channel_info']['TAG_A']['unit'],'кПа')
            save(rows+[metadata('бар'),['','Время','Тег1'],['','2026.01.01 01:00:00,000','1']])
            with self.assertRaisesRegex(ValueError,'единицы'):read_sensor_sheet(path,'CSV')
    def test_single_timestamp_metadata_and_no_time_bucketing(self):
        table=pd.DataFrame([
            ['[1] 10TEST _10TEST [CPU]Температура',None],['Время','[1] _10TEST.1'],
            ['22.06.26 00:00:00:000',1.],['22.06.26 00:10:00:000',2.],
            ['22.06.26 00:29:59:999',3.],['22.06.26 00:30:00:000','X']])
        result=_horizontal(table)
        self.assertEqual(result.index.tolist(),[pd.Timestamp('2026-06-22'),pd.Timestamp('2026-06-22 00:30')])
        self.assertEqual(result['10TEST'].tolist(),[1.,'X'])
        self.assertIn('Температура',result.attrs['channel_info']['10TEST']['description'])
        self.assertEqual(result.attrs['skipped_rows'],2)

    def test_duplicate_tags_and_dates_fail(self):
        for rows in ([['Время','A','A'],['2026-01-01',1,2]],
                     [['Время','A'],['2026-01-01',1],['2026-01-01',2]]):
            with self.assertRaises(ValueError):_horizontal(pd.DataFrame(rows))

    def test_pressure_headers_normalize_without_modifying_inputs(self):
        original=pd.DataFrame([[pd.Timestamp('2026-01-01'),100.,990.,8.,20.,30.,90.,100.,25000.,85.]],
                              columns=['Дата','Pатм, кПа','Pнк, мбар','Ркк, бар','Тнк, °С','Ткк, °С','ВНА','Nприв, МВт','Bприв, нм3/ч','ηoi_cprop'])
        before=original.copy(deep=True)
        result=load_source_data(original)
        self.assertEqual(result.p_atm_pa.iloc[0],100000.)
        self.assertEqual(result.p_nk_pa.iloc[0],99000.)
        self.assertEqual(result.p_kk_mpa.iloc[0],.8)
        prepared=prepare_vna_data(result)
        self.assertEqual(prepared.p.iloc[0],990.)
        self.assertEqual(prepared.pkk.iloc[0],8.)
        pd.testing.assert_frame_equal(original,before)


if __name__=='__main__':unittest.main()
