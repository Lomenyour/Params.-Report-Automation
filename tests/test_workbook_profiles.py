"""Workbook bindings, formula dependencies, current coefficients and portable exports."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
import workbook_profile as wp
from workbook_formulas import FormulaParser, FormulaEvaluator
from data_assembly import SensorMapping, assemble_sensor_data
from result_export import save_result_workbook


def fixture(path, coefficient=.8, extra=False):
    book=Workbook(); sheet=book.active; sheet.title='Данные'
    sheet.append(['Тнк, °С','ВНА','Дата','Pатм, кПа','Pнк, мбар','Ркк, бар',
                  'Ткк, °С','N, МВт','Nприв, МВт','B, нм3/ч','Bприв, нм3/ч',
                  'bприв','ηoi_Cprop','Поправка','Недовыработка','Средняя потеря'])
    for row in (2,3,4):
        sheet.append([20,90,pd.Timestamp('2026-01-01')+pd.Timedelta(minutes=(row-2)*30),
                      101,1000,10,300,100+row,f'=H{row}/N{row}',20000,
                      f'=J{row}*I{row}/H{row}',f'=K{row}/I{row}',84,
                      "='Поправки'!$A$1",'=9/0',f'=O{row}'])
    constants=book.create_sheet('Поправки');constants['A1']=coefficient
    if extra:sheet['A1']='Температура входа'
    book.save(path)


class FormulaTests(unittest.TestCase):
    def run_formula(self,formula,frame=None,constants=None,recipes=None):
        node=FormulaParser(formula,2).parse()
        frame=pd.DataFrame({'A':[2.,3.,4.],'B':[5.,6.,7.]}) if frame is None else frame
        return FormulaEvaluator(frame,recipes or {},constants or {}).evaluate(node)

    def test_arithmetic_conditions_and_blanks_in_ranges(self):
        np.testing.assert_allclose(self.run_formula('IF(A2>2,(A2+B2)^2,0)'),[0,81,121])
        np.testing.assert_allclose(self.run_formula('SUM(A2:B2)'),[7,9,11])
        np.testing.assert_allclose(self.run_formula('AVERAGE(A2:A3)'),[2.5,3.5,4.])
        np.testing.assert_allclose(self.run_formula('IFERROR(A2/0,1)'),[1,1,1])

    def test_relative_rows_and_cross_sheet_absolute_constants(self):
        np.testing.assert_allclose(self.run_formula("A2*'Своя поправка'!$C$8",constants={'Своя поправка!C8':.5}),[1,1.5,2])
        result=self.run_formula('A3-A2');np.testing.assert_allclose(result[:2],[1,1]);self.assertTrue(np.isnan(result[-1]))

    def test_unsupported_external_and_code_like_expressions_rejected(self):
        for text in ('SHELL("anything")','__import__("os")',"'[other.xlsx]Sheet1'!A2",'UNSUPPORTED(A2)'):
            with self.subTest(text=text),self.assertRaises(ValueError):FormulaParser(text,2).parse()

    def test_cycles_raise_before_writing_calculated_values(self):
        recipes={col:{'node':FormulaParser(formula,2).parse()} for col,formula in {'A':'B2+1','B':'A2+1'}.items()}
        with self.assertRaisesRegex(ValueError,'Циклическая'):FormulaEvaluator(pd.DataFrame({'A':[1],'B':[2]}),recipes,{}).column('A')

    def test_aggregate_does_not_hide_calculated_error_and_round_matches_excel(self):
        recipes={'A':{'node':FormulaParser('1/0',2).parse()}}
        self.assertTrue(np.isnan(self.run_formula('SUM(A2:B2)',recipes=recipes)).all())
        np.testing.assert_allclose(self.run_formula('ROUND(A2,0)',frame=pd.DataFrame({'A':[.5,-.5,2.5]})),[1,-1,3])


class WorkbookProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.path=self.root/'book.xlsx';fixture(self.path)
        self.store=self.root/'profiles.json'
        self.patch=patch.object(wp,'profile_path',return_value=self.store);self.patch.start();self.addCleanup(self.patch.stop)
        self.layout=wp.read_layout(self.path)

    def setup_book(self,save=False):
        rows=wp.suggestions(self.layout,'station','1')
        # Cached/manual compressor efficiency is intentionally not a formula in this fixture.
        return wp.confirm(self.layout,'station','1',rows,save=save)

    def test_bindings_use_headers_not_excel_positions(self):
        setup=self.setup_book()
        self.assertEqual(setup.bindings['date']['column'],'C')
        self.assertEqual(setup.bindings['t']['column'],'A')
        data=self.layout.values.copy();setup.recalculate(data)
        canonical=setup.canonical(data)
        np.testing.assert_allclose(canonical.power,[102/.8,103/.8,104/.8])
        np.testing.assert_allclose(canonical.p_atm_pa,101000)
        np.testing.assert_allclose(canonical.p_nk_pa,100000)
        np.testing.assert_allclose(canonical.p_kk_mpa,1)
        self.assertNotIn('O',setup.recipes);self.assertNotIn('P',setup.recipes)

    def test_confirmation_only_saves_mappings_not_coefficients(self):
        rows=wp.suggestions(self.layout,'station','1')
        self.assertFalse(self.store.exists())
        wp.confirm(self.layout,'station','1',rows,save=True)
        saved=json.loads(self.store.read_text())
        self.assertNotIn('constants',saved['profiles']['station|1']['current'])
        self.assertNotIn('coefficients',saved['profiles']['station|1']['current'])
        self.assertTrue(wp.suggestions(self.layout,'station','1'))

    def test_explicit_pressure_meaning_has_priority_over_legacy_ratio_guess(self):
        from data_loader import prepare_vna_data
        setup=self.setup_book();frame=self.layout.values.copy();setup.recalculate(frame)
        source=setup.canonical(frame);source['p_nk_pa']=10000.
        prepared=prepare_vna_data(source)
        np.testing.assert_allclose(prepared.p,100.)

    def test_coefficients_come_from_current_book(self):
        self.setup_book(save=True)
        fixture(self.path,coefficient=.5)
        self.layout=wp.read_layout(self.path)
        setup=self.setup_book();data=self.layout.values.copy();setup.recalculate(data)
        self.assertEqual(data.I.iloc[0],204)

    def test_mapping_moves_with_unique_header_and_keeps_history(self):
        self.setup_book(save=True)
        book=load_workbook(self.path); sheet=book['Данные'];sheet['A1']='Температура входа';book.save(self.path)
        layout=wp.read_layout(self.path);rows=wp.suggestions(layout,'station','1')
        row=next(row for row in rows if row['column']=='A');row['role']='t';row['unit']='°C'
        wp.confirm(layout,'station','1',rows,save=True)
        data=json.loads(self.store.read_text());self.assertEqual(len(data['profiles']['station|1']['history']),1)
        restored=wp.suggestions(self.layout,'station','1')
        self.assertEqual(next(row for row in restored if row['column']=='A')['role'],'t')

    def test_missing_required_and_duplicate_roles_rejected(self):
        rows=wp.suggestions(self.layout,'station','1');rows[0]['role']=''
        with self.assertRaisesRegex(ValueError,'Назначьте'):wp.confirm(self.layout,'station','1',rows,save=False)
        rows[0]['role']='vna'
        rows[0]['unit']='%'
        with self.assertRaisesRegex(ValueError,'дважды'):wp.confirm(self.layout,'station','1',rows,save=False)

    def test_import_needs_formula_for_computed_parameters(self):
        with self.assertRaisesRegex(ValueError,'КПД'):wp.validate_recalculation(self.setup_book())

    def test_two_variants_are_visible_and_selection_controls_calculation(self):
        book=load_workbook(self.path);book['Данные']['N2']='=1';book['Данные']['N3']='=0.5';book['Данные']['N4']='=0.5';book.save(self.path)
        layout=wp.read_layout(self.path);rows=wp.suggestions(layout,'station','1')
        self.assertEqual(len(layout.variants['N']),2)
        selected=next(row for row in rows if row['column']=='N')
        self.assertTrue(selected['recipe'])
        setup=wp.confirm(layout,'station','1',rows,save=False);data=layout.values.copy();setup.recalculate(data)
        np.testing.assert_allclose(data.I,[204,206,208])

    def test_embedded_profile_roundtrip_keeps_calculation_without_original_sheets(self):
        setup=self.setup_book();values=self.layout.values.copy();setup.recalculate(values)
        from data_assembly import AssembledData
        data=AssembledData(values,self.layout.headers,0,0,{},[])
        destination=self.root/'result.xlsx'
        save_result_workbook(data,[],destination,book_profile=setup.metadata())
        loaded=wp.read_layout(destination)
        self.assertTrue(loaded.variants)
        fresh=wp.confirm(loaded,'station','1',wp.suggestions(loaded,'station','1'),save=False)
        frame=loaded.values.copy();frame.loc[0,'H']=200;fresh.recalculate(frame)
        self.assertEqual(frame.I.iloc[0],250)

    def test_exported_custom_binding_survives_without_local_mapping_and_large_metadata(self):
        self.layout.headers['A']='Датчик №42'
        rows=wp.suggestions(self.layout,'station','1');rows[0]['role']='t';rows[0]['unit']='°C'
        setup=wp.confirm(self.layout,'station','1',rows,save=False)
        setup.constants.update({f'Группа коэффициентов {i}!A1':i+.5 for i in range(900)})
        frame=self.layout.values.copy();setup.recalculate(frame)
        from data_assembly import AssembledData
        data=AssembledData(frame,setup.import_headers(self.layout.headers),0,0,{},[])
        path=self.root/'portable.xlsx';save_result_workbook(data,[],path,book_profile=setup.metadata())
        layout=wp.read_layout(path)
        restored=wp.confirm(layout,'station','1',wp.suggestions(layout,'station','1'),save=False)
        self.assertEqual(restored.bindings['t']['column'],'A')
        self.assertEqual(restored.constants['Группа коэффициентов 899!A1'],899.5)
        with self.assertRaisesRegex(ValueError,'другой ТЭЦ'):
            wp.confirm(layout,'other_station','1',wp.suggestions(layout,'other_station','1'),save=False)

    def test_import_respects_mapped_date_and_sensor_columns(self):
        setup=self.setup_book()
        raw=pd.DataFrame({'TEMP':[25.,26.]},index=pd.to_datetime(['2026-01-01 00:30','2026-01-01 01:30']))
        with patch('data_assembly._read_sensor_sheet',return_value=raw),patch('data_assembly.source_selection_info',return_value={}):
            merged=assemble_sensor_data(self.path,self.path,'Sheet1',[SensorMapping('TEMP','A')],
                station_id='syz_tec',unit='10',book_setup=setup)
        self.assertEqual(merged.overlap_rows,1);self.assertEqual(len(merged.values),4)
        self.assertEqual(merged.values.loc[pd.Timestamp('2026-01-01 00:30'),'A'],25)
        self.assertEqual(merged.values.loc[pd.Timestamp('2026-01-01 01:30'),'C'],pd.Timestamp('2026-01-01 01:30'))

    def test_ready_and_import_export_app_losses_for_station_header_alias(self):
        from data_assembly import AssembledData,apply_economic_columns
        from result_export import read_data_sheet
        book=load_workbook(self.path);book['Данные']['O1']='Перерасход газа';book['Данные']['P1']=None;book.save(self.path)
        layout=wp.read_layout(self.path)
        losses={'row_losses':pd.DataFrame({'date':pd.to_datetime(layout.values.C),'period':[1,1,1],
                                         'fuel_loss_rate':[10.,20.,30.],'power_loss_rate':[1.,2.,3.]})}
        imported=layout.values.copy();imported.index=pd.DatetimeIndex(imported.C)
        data=AssembledData(imported,layout.headers,0,0,{},[]);apply_economic_columns(data,losses)
        ready=read_data_sheet(self.path);ready.apply_economic_result(losses,'C')
        np.testing.assert_allclose(data.values.O,[10,20,30])
        np.testing.assert_allclose(pd.to_numeric(ready.values.iloc[1:,14]),[10,20,30])
        self.assertEqual(data.values.P.iloc[1],15)
        self.assertEqual(ready.values.iat[2,15],15)
        np.testing.assert_allclose(pd.to_numeric(ready.values.iloc[1:,3]),101)

    def test_adding_confirmed_header_to_unnamed_numeric_column_preserves_values(self):
        from result_export import read_data_sheet
        book=load_workbook(self.path);book['Данные']['A1']=None;book.save(self.path)
        data=read_data_sheet(self.path);before=data.values.iloc[1:,0].copy()
        data.apply_headers({'A':'Температура перед компрессором, °C'})
        self.assertEqual(data.values.iat[0,0],'Температура перед компрессором, °C')
        np.testing.assert_allclose(pd.to_numeric(data.values.iloc[1:,0]),pd.to_numeric(before))

    def test_recalculation_preserves_unchanged_cached_history_with_missing_sensor(self):
        setup=self.setup_book();frame=self.layout.values.copy()
        frame.loc[0,'H']=None;frame.loc[0,'I']=99.;frame.loc[0,'K']=123.;frame.loc[0,'L']=1.2
        changed=pd.DatetimeIndex([frame.loc[1,'C']])
        setup.recalculate(frame,changed_dates=changed)
        self.assertEqual(frame.I.iloc[0],99.)
        self.assertEqual(frame.K.iloc[0],123.)
        self.assertEqual(frame.I.iloc[1],103/.8)

    def test_dated_gas_density_is_used_in_recognized_mass_volume_conversion(self):
        from gas_passport import GasPassport
        book=load_workbook(self.path);sheet=book['Данные'];sheet['J1']='B, кг/с'
        for row in (2,3,4):sheet[f'K{row}']=f'=J{row}*3600/0.7'
        book.save(self.path)
        layout=wp.read_layout(self.path);setup=wp.confirm(layout,'station','1',wp.suggestions(layout,'station','1'),save=False)
        passport=GasPassport('station','1',1.4,35.,3.)
        frame=layout.values.copy();setup.recalculate(frame,passport=passport)
        np.testing.assert_allclose(frame.K,20000*3600/1.4)


if __name__=='__main__':unittest.main()
