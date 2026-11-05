"""Notation preserves AST semantics; hiding rows never removes computations."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from formula_display import FormulaNotation,PARAMETER_SYMBOLS,parameter_symbols
from workbook_formulas import FormulaParser
from workbook_mapping_ui import formula_view,dialog_payload,merge_mapping_rows
import workbook_profile as wp
from test_workbook_profiles import fixture


class FormulaNotationTests(unittest.TestCase):
    def test_parentheses_power_and_unary_roundtrip_to_same_ast(self):
        for source in ('A2/(B2*C2)','A2/(B2/C2)','A2-(B2+C2)','A2+(B2-C2)',
                       'A2*(B2/C2)','(A2+B2)^2','-A2^2','(-A2)^2',
                       'A2^(B2^C2)','(A2^B2)^C2','A2^(-B2)','-(A2+B2)',
                       'A2/(B2+C2)','A2-(B2-C2)','(A2<B2)=C2',
                       'A2<=(B2+C2)','A2<>(B2<C2)'):
            with self.subTest(source=source):
                node=FormulaParser(source,2).parse()
                pretty=FormulaNotation({'A':'A2','B':'B2','C':'C2'}).render(node)
                restored=pretty.replace('×','*').replace('−','-').replace('²','^2').replace('³','^3').replace('≤','<=').replace('≥','>=').replace('≠','<>')
                self.assertEqual(node,FormulaParser(restored,2).parse(),pretty)

    def test_symbols_do_not_confuse_absolute_and_specific_flow(self):
        self.assertEqual(PARAMETER_SYMBOLS['fuel'],'Bприв')
        self.assertEqual(PARAMETER_SYMBOLS['fuel_specific'],'bприв')
        self.assertEqual(PARAMETER_SYMBOLS['correction_temperature_power'],'kTN')

    def test_relative_rows_and_coolprop_arguments_are_visible(self):
        node=FormulaParser('AVERAGE(A2:A4)',2).parse()
        text=FormulaNotation({'A':'Nизм'}).render(node)
        self.assertEqual(text,'СРЕДНЕЕ(Nизм; Nизм[t+1]; Nизм[t+2])')
        node=FormulaParser('PropsSI("H","T",A2+273.15,"P",B2,"Air")',2).parse()
        text=FormulaNotation({'A':'Tнк','B':'Pнк'}).render(node)
        self.assertIn('CoolProp.PropsSI("H"; "T"; Tнк + 273.15',text)

    def test_coefficient_symbols_are_local_unique_and_reused(self):
        node=['binary','+', ['constant','coefficients','one'],['binary','*',['constant','coefficients','two'],['constant','coefficients','one']]]
        formatter=FormulaNotation({})
        self.assertEqual(formatter.render(node),'c₁ + c₂ × c₁')
        self.assertEqual(formatter.coefficients,{'one':'c₁','two':'c₂'})

    def test_duplicate_and_operator_containing_headers_get_unambiguous_symbols(self):
        columns=[{'column':'A','header':'X','role':''},{'column':'B','header':'X','role':''},
                 {'column':'C','header':'ФГО+ФТО','role':''},{'column':'D','header':'','role':''}]
        result=parameter_symbols(columns,{c:c for c in 'ABCD'})
        self.assertEqual(len(set(result.values())),4)
        self.assertEqual(result['C'],'«ФГО+ФТО»');self.assertEqual(result['D'],'вспом_1')


class FormulaViewTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'book.xlsx';fixture(self.path)
        patcher=patch.object(wp,'profile_path',return_value=self.root/'profile.json');patcher.start();self.addCleanup(patcher.stop)

    def read(self):
        layout=wp.read_layout(self.path);return layout,wp.suggestions(layout,'station','1')

    def test_reduced_power_uses_named_parameters_and_coefficients_keep_sources(self):
        book=load_workbook(self.path);book['Данные']['N1']='kTN';book.save(self.path)
        layout,rows=self.read();before=copy.deepcopy(rows)
        view=formula_view(layout,rows)
        power=next(row for row in view['rows'] if row['column']=='I')
        correction=next(row for row in view['rows'] if row['column']=='N')
        self.assertEqual(power['display_formula'],'Nприв = Nизм / kTN')
        self.assertEqual(correction['display_formula'],'kTN = c₁')
        self.assertEqual(correction['coefficients'][0]['source'],'Поправки!A1')
        self.assertEqual(correction['coefficients'][0]['value'],.8)
        self.assertEqual(rows,before);self.assertFalse((self.root/'profile.json').exists())

    def test_unsaved_mapping_changes_preview_without_changing_recipe(self):
        layout,rows=self.read();old=copy.deepcopy(layout.variants)
        rows[13]['role']='correction_temperature_efficiency'
        power=next(row for row in formula_view(layout,rows)['rows'] if row['column']=='I')
        self.assertEqual(power['display_formula'],'Nприв = Nизм / kTη')
        self.assertEqual(layout.variants,old)

    def test_hidden_dependency_is_preserved_through_confirmation_and_portable_export(self):
        book=load_workbook(self.path);sheet=book['Данные'];sheet['Q1']=None;sheet['R1']='Дополнительный датчик'
        for row in (2,3,4):sheet[f'R{row}']=0
        for row in (2,3,4):sheet[f'Q{row}']=f'=H{row}+1';sheet[f'I{row}']=f'=Q{row}/N{row}'
        book.save(self.path)
        layout,rows=self.read();payload=dialog_payload(layout,rows)
        self.assertNotIn('Q',{row['column'] for row in payload['rows']})
        merged=merge_mapping_rows(layout,rows,payload['rows'])
        setup=wp.confirm(layout,'station','1',merged,save=False)
        values=layout.values.copy();setup.recalculate(values)
        np.testing.assert_allclose(values.I,[103/.8,104/.8,105/.8])
        self.assertIn('Q',setup.recipes)
        from data_assembly import AssembledData
        from result_export import save_result_workbook
        destination=self.root/'result.xlsx'
        save_result_workbook(AssembledData(values,layout.headers,0,0,{},[]),[],destination,book_profile=setup.metadata())
        reloaded=wp.read_layout(destination)
        fresh=wp.confirm(reloaded,'station','1',wp.suggestions(reloaded,'station','1'),save=False)
        frame=reloaded.values.copy();frame.loc[0,'H']=200;fresh.recalculate(frame)
        self.assertAlmostEqual(frame.I.iloc[0],201/.8)

    def test_hidden_row_cannot_be_injected_from_client(self):
        layout,rows=self.read();layout.headers['N']=None;rows[13]['header']=''
        payload=dialog_payload(layout,rows)
        with self.assertRaisesRegex(ValueError,'видимых'):merge_mapping_rows(layout,rows,payload['rows']+[rows[13]])
        for invalid in (None,42,['not a row']):
            with self.assertRaisesRegex(ValueError,'видимых'):merge_mapping_rows(layout,rows,invalid)

    def test_hidden_named_measurement_keeps_mapping_unit_and_identity(self):
        layout,rows=self.read();layout.headers['H']=None;rows[7]['header']=''
        visible=dialog_payload(layout,rows)['rows']
        self.assertNotIn('H',{row['column'] for row in visible})
        merged=merge_mapping_rows(layout,rows,visible)
        setup=wp.confirm(layout,'station','1',merged,save=False)
        self.assertEqual(setup.bindings['power_n']['column'],'H')
        self.assertEqual(setup.bindings['power_n']['unit'],'МВт')

    def test_legacy_losses_are_labelled_program_calculations_not_old_formulas(self):
        layout,rows=self.read()
        for row in formula_view(layout,rows)['rows']:
            if row['column'] in ('O','P'):
                self.assertTrue(row['application_owned']);self.assertEqual(row['display_formula'],'')


if __name__=='__main__':unittest.main()
