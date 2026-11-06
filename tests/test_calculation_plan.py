"""Only mapped outputs and necessary helpers may be extended onto imported rows."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
import workbook_profile as wp
from workbook_mapping_ui import formula_view,dialog_payload
from workbook_model import CalculationModel
from test_workbook_profiles import fixture


class CalculationPlanTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'book.xlsx';fixture(self.path)
        book=load_workbook(self.path)
        for row in (2,3,4):book['Данные'][f'M{row}']=f'=84+H{row}*0'
        book.save(self.path)
        patched=patch.object(wp,'profile_path',return_value=self.root/'profiles.json')
        patched.start();self.addCleanup(patched.stop)

    def prepare(self,edit):
        book=load_workbook(self.path);edit(book['Данные']);book.save(self.path)
        layout=wp.read_layout(self.path);rows=wp.suggestions(layout,'station','1')
        return layout,rows,wp.confirm(layout,'station','1',rows,save=False)

    def test_unrelated_cycles_are_preserved_but_required_helpers_are_selected(self):
        def edit(sheet):
            sheet['Q1']='Старая сводка';sheet['R1']='Продолжение сводки'
            for row in (2,3,4):
                sheet[f'Q{row}']=f'=R{row}+1';sheet[f'R{row}']=f'=Q{row}+1'
        layout,rows,setup=self.prepare(edit)
        wp.validate_recalculation(setup)
        self.assertNotIn('Q',setup.recipes);self.assertNotIn('R',setup.recipes)
        self.assertIn('N',setup.recipes) # Unassigned, but required by Nприв.
        plan=setup.metadata()['calculation_plan']
        self.assertIn('N',plan['dependencies']);self.assertIn('I',plan['targets'])
        values=layout.values.copy();values['Q']=[7,8,9];values['R']=[3,4,5]
        setup.recalculate(values)
        self.assertEqual(values.Q.tolist(),[7,8,9]);self.assertEqual(values.R.tolist(),[3,4,5])
        np.testing.assert_allclose(values.I,[127.5,128.75,130.])
        view=formula_view(layout,rows)
        self.assertEqual(view['plan'],plan)
        self.assertEqual(next(row for row in view['rows'] if row['column']=='Q')['calculation_status'],'preserved')

    def test_unrelated_conflicting_formulas_do_not_block_import(self):
        def edit(sheet):
            sheet['Q1']='Посторонний итог';sheet['Q2']='=1';sheet['Q3']='=2';sheet['Q4']=1
        layout,rows,setup=self.prepare(edit)
        self.assertTrue(next(row for row in setup.columns if row['column']=='Q')['formula_conflict'])
        wp.validate_recalculation(setup)
        self.assertNotIn('Q',setup.recipes)
        self.assertNotIn('Нет единственной основной формулы',dialog_payload(layout,rows)['note'])

    def test_required_conflict_fails_before_computing(self):
        def edit(sheet):
            sheet['Q1']='Промежуточная поправка';sheet['Q2']='=1';sheet['Q3']='=2';sheet['Q4']=1
            for row in (2,3,4):sheet[f'I{row}']=f'=H{row}/Q{row}'
        _,_,setup=self.prepare(edit)
        with self.assertRaisesRegex(ValueError,'Q.*одинаково часто'):wp.validate_recalculation(setup)

    def test_required_cycle_fails_during_validation_without_mutating_values(self):
        def edit(sheet):
            sheet['Q1']='Поправка один';sheet['R1']='Поправка два'
            for row in (2,3,4):
                sheet[f'Q{row}']=f'=R{row}+1';sheet[f'R{row}']=f'=Q{row}+1'
                sheet[f'I{row}']=f'=H{row}/Q{row}'
        layout,_,setup=self.prepare(edit)
        before=layout.values.copy(deep=True)
        with self.assertRaisesRegex(ValueError,'Циклическая.*Поправка один.*Поправка два'):
            wp.validate_recalculation(setup)
        with self.assertRaisesRegex(ValueError,'Циклическая'):setup.recalculate(layout.values)
        pd.testing.assert_frame_equal(layout.values,before)

    def test_explicitly_mapped_optional_calculation_is_selected(self):
        def edit(sheet):
            sheet['Q1']='kTη'
            for row in (2,3,4):sheet[f'Q{row}']=f'=H{row}/100'
        layout,_,setup=self.prepare(edit)
        self.assertIn('Q',setup.metadata()['calculation_plan']['targets'])
        values=layout.values.copy();setup.recalculate(values)
        np.testing.assert_allclose(values.Q,[1.02,1.03,1.04])

    def test_unknown_reference_is_ignored_only_outside_the_plan(self):
        def edit(sheet):
            sheet['Q1']='Чужая формула'
            for row in (2,3,4):sheet[f'Q{row}']=f'=ZZ{row}+1'
        _,_,setup=self.prepare(edit);wp.validate_recalculation(setup)
        def depend(sheet):
            for row in (2,3,4):sheet[f'I{row}']=f'=H{row}/Q{row}'
        _,_,setup=self.prepare(depend)
        with self.assertRaisesRegex(ValueError,'не найден.*ZZ'):wp.validate_recalculation(setup)

    def test_plan_survives_mapping_save_and_portable_workbook(self):
        from data_assembly import AssembledData
        from result_export import save_result_workbook
        layout,rows,setup=self.prepare(lambda sheet:None)
        wp.confirm(layout,'station','1',rows,save=True)
        restored=wp.confirm(layout,'station','1',wp.suggestions(layout,'station','1'),save=False)
        self.assertEqual(restored.metadata()['calculation_plan'],setup.metadata()['calculation_plan'])
        values=layout.values.copy();setup.recalculate(values)
        target=self.root/'portable.xlsx'
        save_result_workbook(AssembledData(values,layout.headers,0,0,{},[]),[],target,book_profile=setup.metadata())
        exported=wp.read_layout(target)
        portable=wp.confirm(exported,'station','1',wp.suggestions(exported,'station','1'),save=False)
        wp.validate_recalculation(portable)
        self.assertEqual(portable.metadata()['calculation_plan'],setup.metadata()['calculation_plan'])

    def test_unassigned_preserved_columns_keep_their_kind_in_portable_export(self):
        from data_assembly import AssembledData
        from result_export import save_result_workbook
        def edit(sheet):
            sheet['Q1']=None;sheet['R1']='Промежуточный итог';sheet['S1']='Промежуточный итог'
            for row in (2,3,4):
                for column in ('Q','R','S'):sheet[f'{column}{row}']=f'=H{row}*2'
            sheet['T5']=0.
        layout,_,setup=self.prepare(edit);values=layout.values.iloc[:3].copy()
        for column in ('Q','R','S'):values[column]=[204.,206.,208.]
        target=self.root/'preserved.xlsx'
        save_result_workbook(AssembledData(values,layout.headers,0,0,{},[]),[],target,book_profile=setup.metadata())
        exported=wp.read_layout(target)
        portable=wp.confirm(exported,'station','1',wp.suggestions(exported,'station','1'),save=False)
        self.assertEqual(portable.metadata()['calculation_plan'],setup.metadata()['calculation_plan'],
                         [(row['column'],row['header'],exported.headers.get(row['column'])) for row in exported.embedded_columns])
        for column in ('Q','R','S'):
            self.assertEqual(next(row['kind'] for row in portable.columns if row['column']==column),'computed')
            self.assertNotIn(column,portable.recipes)
        moved=copy.deepcopy(exported);moved.headers['A'],moved.headers['B']=moved.headers['B'],moved.headers['A']
        self.assertEqual(next(row['kind'] for row in wp.suggestions(moved,'station','1') if row['column']=='Q'),'measured')

    def test_mapped_measured_formula_is_kept_as_input(self):
        layout,rows,_=self.prepare(lambda sheet:None)
        next(row for row in rows if row['column']=='M')['kind']='measured'
        setup=wp.confirm(layout,'station','1',rows,save=False)
        values=layout.values.copy();values['M']=[81.,82.,83.]
        setup.recalculate(values)
        self.assertNotIn('M',setup.recipes)
        self.assertEqual(values.M.tolist(),[81.,82.,83.])

    def test_mapped_optional_calculation_cannot_fall_back_to_cached_values(self):
        def edit(sheet):
            sheet['Q1']='Температура топлива, °C'
            for row in (2,3,4):sheet[f'Q{row}']=20.
        layout,rows,_=self.prepare(edit)
        next(row for row in rows if row['column']=='Q').update(role='gas_temperature',kind='computed')
        setup=wp.confirm(layout,'station','1',rows,save=False)
        self.assertNotIn('Q',setup.metadata()['calculation_plan']['preserved'])
        with self.assertRaisesRegex(ValueError,'нет формулы.*Температура топлива'):wp.validate_recalculation(setup)

    def test_neutral_model_orders_only_requested_parameters(self):
        parameters={key:{'label':key,'kind':'computed' if key!='measured' else 'measured'}
                    for key in ('measured','helper','output','old_summary')}
        model=CalculationModel(parameters,{'helper':{'node':['data','measured',0]},
                    'output':{'node':['data','helper',0]},'old_summary':{'node':['data','old_summary',-1]}},{})
        self.assertEqual(model.execution_order(['output']),['helper','output'])
        with self.assertRaisesRegex(ValueError,'Циклическая'):model.execution_order(['old_summary'])


if __name__=='__main__':unittest.main()
