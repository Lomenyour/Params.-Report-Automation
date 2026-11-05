"""Semantic correction roles, persisted mappings and storage-independent recipes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
import workbook_profile as wp
from workbook_corrections import correction_role
from workbook_formulas import references
from workbook_model import CalculationModel
from workbook_mapping_ui import corrections_payload, dialog_payload
from test_workbook_profiles import fixture


class WorkbookModelTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'book.xlsx';fixture(self.path)
        self.store=self.root/'profiles.json'
        patched=patch.object(wp,'profile_path',return_value=self.store);patched.start();self.addCleanup(patched.stop)

    def read(self,station='station',unit='1',save=False):
        layout=wp.read_layout(self.path);rows=wp.suggestions(layout,station,unit)
        return layout,rows,wp.confirm(layout,station,unit,rows,save=save)

    def test_correction_symbols_have_separate_roles(self):
        expected={'kTη':'temperature_efficiency','kTN':'temperature_power','kPN':'atmospheric_pressure_power',
                  'kPη':'atmospheric_pressure_efficiency','kφN':'humidity_power','kφη':'humidity_efficiency',
                  'kΔPвхN':'inlet_loss_power','kΔPнкη':'inlet_loss_efficiency','kΔPвыхη':'outlet_loss_efficiency',
                  'ktгN':'fuel_temperature_power','k(c/h)N':'fuel_properties_power','knN':'speed_power',
                  'kn/n0N':'speed_power','kn/n₀N':'speed_power'}
        for header,key in expected.items():
            with self.subTest(header=header):self.assertEqual(correction_role(header),'correction_'+key)
        self.assertEqual(correction_role('Поправка'),'')

    def test_legacy_helper_is_upgraded_but_new_explicit_helper_is_preserved(self):
        book=load_workbook(self.path);book['Данные']['N1']='kTN';book.save(self.path)
        layout,rows,setup=self.read(save=True)
        self.assertEqual(setup.bindings['correction_temperature_power']['column'],'N')
        data=json.loads(self.store.read_text());row=data['profiles']['station|1']['current']['columns'][13]
        row['role']='';row.pop('mapping_version');self.store.write_text(json.dumps(data))
        self.assertEqual(self.read()[1][13]['role'],'correction_temperature_power')
        rows=wp.suggestions(layout,'station','1');rows[13]['role']=''
        wp.confirm(layout,'station','1',rows,save=True)
        self.assertEqual(wp.suggestions(layout,'station','1')[13]['role'],'')

    def test_saved_mapping_is_scoped_by_station_and_unit(self):
        layout,rows,_=self.read();rows[13].update(role='correction_temperature_power',unit='о.е.')
        wp.confirm(layout,'station','1',rows,save=True)
        self.assertEqual(wp.suggestions(layout,'station','1')[13]['role'],'correction_temperature_power')
        self.assertEqual(wp.suggestions(layout,'station','2')[13]['role'],'')
        self.assertEqual(wp.suggestions(layout,'other_station','1')[13]['role'],'')

    def test_unnamed_column_mapping_restores_only_for_same_ordered_layout(self):
        book=load_workbook(self.path);book['Данные']['N1']=None;book.save(self.path)
        layout,rows,_=self.read();rows[13].update(role='correction_temperature_power',unit='о.е.')
        wp.confirm(layout,'station','1',rows,save=True)
        self.assertEqual(wp.suggestions(layout,'station','1')[13]['role'],'correction_temperature_power')
        moved=copy.deepcopy(layout);moved.headers['A'],moved.headers['B']=moved.headers['B'],moved.headers['A']
        self.assertEqual(wp.suggestions(moved,'station','1')[13]['role'],'')

    def test_explicit_unnamed_helper_is_not_overwritten_by_hours_hint(self):
        layout,rows,_=self.read();layout.headers['A']=None;layout.headers['B']='Дата'
        saved=[{'column':'A','header':'','role':'','unit':'','kind':'measured','mapping_version':2}]
        self.store.write_text(json.dumps({'schema_version':1,'profiles':{'station|1':{'current':{
            'columns':saved,'ordered_signature':wp.node_id(list(layout.headers.values()))},'history':[]}}}))
        self.assertEqual(wp.suggestions(layout,'station','1')[0]['role'],'')

    def test_majority_overrides_previous_minority_choice_and_qualified_refs_group(self):
        book=load_workbook(self.path);sheet=book['Данные']
        sheet['N2']="='Данные'!H2/100";sheet['N3']='=Данные!H3/100';sheet['N4']='=0.5';book.save(self.path)
        layout,rows,_=self.read(save=True)
        self.assertEqual(sorted(v['count'] for v in layout.variants['N']),[1,2])
        data=json.loads(self.store.read_text());data['profiles']['station|1']['current']['columns'][13]['recipe']=next(v['id'] for v in layout.variants['N'] if v['count']==1)
        self.store.write_text(json.dumps(data))
        restored=wp.suggestions(layout,'station','1')
        selected=next(v for v in layout.variants['N'] if v['id']==restored[13]['recipe'])
        self.assertEqual(selected['count'],2)
        self.assertTrue(restored[13]['changed'])

    def test_equal_frequency_formulas_block_import_without_arbitrary_choice(self):
        book=load_workbook(self.path);sheet=book['Данные'];sheet['N2']='=1';sheet['N3']='=2';sheet['N4']=.8;book.save(self.path)
        _,rows,setup=self.read()
        self.assertEqual(rows[13]['recipe'],'')
        with self.assertRaisesRegex(ValueError,'одинаково часто'):wp.validate_recalculation(setup)

    def test_service_columns_and_corrections_cannot_be_sensor_destinations(self):
        book=load_workbook(self.path);book['Данные']['N1']='kTN';book.save(self.path)
        layout,rows,setup=self.read()
        self.assertEqual(rows[2]['kind'],'service');self.assertNotIn('N',setup.sensor_columns.values())
        rows[13]['kind']='measured'
        with self.assertRaisesRegex(ValueError,'расчётный тип'):wp.confirm(layout,'station','1',rows,save=False)

    def test_constant_correction_is_visible_and_extends_but_partial_or_varying_is_rejected(self):
        book=load_workbook(self.path);sheet=book['Данные'];sheet['N1']='kPη'
        for row in (2,3,4):sheet[f'N{row}']=1.
        book.save(self.path)
        layout,rows,setup=self.read()
        self.assertTrue(setup.recipes['N']['constant_value'])
        self.assertNotIn('Постоянные поправки',dialog_payload(layout,rows)['note'])
        from workbook_mapping_ui import formula_view
        self.assertTrue(next(item for item in formula_view(layout,rows)['rows'] if item['column']=='N')['constant_value'])
        values=layout.values.copy();values.loc[3]=values.loc[2];values.loc[3,'N']=None
        setup.recalculate(values);self.assertEqual(values.N.iloc[3],1.)
        for replacement in (None,2.):
            sheet['N4']=replacement;book.save(self.path)
            layout,rows,setup=self.read()
            self.assertNotIn('N',setup.recipes)
            with self.assertRaisesRegex(ValueError,'нет формулы'):wp.validate_recalculation(setup)

    def test_neutral_model_roundtrip_evaluates_without_excel_addresses(self):
        layout,_,setup=self.read();metadata=setup.metadata()
        model=CalculationModel.from_dict(metadata['calculation_model'])
        ids=metadata['source_bindings']['columns']
        for recipe in model.recipes.values():
            self.assertTrue(all(ref[1] in model.parameters for ref in references(recipe['node'],'data')))
            self.assertTrue(all(ref[1]=='coefficients' for ref in references(recipe['node'],'constant')))
        frame=layout.values.rename(columns=ids)
        np.testing.assert_allclose(model.evaluator(frame).column('power'),[127.5,128.75,130.])
        frame.loc[0,'power_n']=200
        self.assertEqual(model.evaluator(frame).column('power')[0],250.)
        model.coefficients[next(iter(model.coefficients))]=.5
        self.assertNotEqual(model.to_dict()['revision'],metadata['calculation_model']['revision'])
        damaged=copy.deepcopy(metadata['calculation_model']);damaged['coefficients']['extra']=1
        with self.assertRaisesRegex(ValueError,'содержимому'):CalculationModel.from_dict(damaged)

    def test_identical_correction_expressions_remain_distinct_and_coefficients_are_visible(self):
        book=load_workbook(self.path);sheet=book['Данные'];sheet['N1']='kTN';sheet['Q1']='kTη'
        for row in (2,3,4):sheet[f'Q{row}']="='Поправки'!$A$1"
        book.save(self.path)
        layout,rows,setup=self.read();model=setup.metadata()['calculation_model']
        self.assertIn('correction_temperature_power',model['recipes'])
        self.assertIn('correction_temperature_efficiency',model['recipes'])
        groups=corrections_payload(setup)['groups']
        self.assertEqual(sum(g['label'].startswith('Поправка температуры') for g in groups),2)
        self.assertTrue(all(g['coefficients'][0]['value']==.8 for g in groups if g['column'] in ('N','Q')))
        payload=dialog_payload(layout,rows)
        self.assertNotIn('несколько вариантов',payload['note'])
        self.assertTrue(next(row for row in payload['rows'] if row['column']=='P')['application_owned'])

    def test_changed_neighbor_average_is_updated_while_unrelated_history_is_preserved(self):
        book=load_workbook(self.path);sheet=book['Данные'];sheet['Q1']='Среднее'
        for row in (2,3,4):sheet[f'Q{row}']=f'=AVERAGE(H{row}:H{row+1})'
        book.save(self.path)
        layout,_,setup=self.read();values=layout.values.copy();values['Q']=[102.5,103.5,777.]
        values.loc[1,'H']=200
        setup.recalculate(values,changed_dates=pd.DatetimeIndex([values.loc[1,'C']]))
        self.assertEqual(values.Q.iloc[0],151.)
        self.assertEqual(values.Q.iloc[1],152.)
        self.assertEqual(values.Q.iloc[2],777.)


if __name__=='__main__':unittest.main()
