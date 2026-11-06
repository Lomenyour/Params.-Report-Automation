"""Legacy financial panels beside dated rows must not become row recipes."""
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
from workbook_formulas import data_reference_columns, FormulaParser, FormulaEvaluator
from data_assembly import AssembledData
from result_export import save_result_workbook
from test_workbook_profiles import fixture


class ReferenceInspectionTests(unittest.TestCase):
    def test_unsupported_function_and_long_absolute_ranges_are_inspected_not_evaluated(self):
        formula='SUMIF(\'Данные\'!$BB$2:$BC$50000,">0",$BD$2:$BD$50000)'
        self.assertEqual(data_reference_columns(formula),{'BB','BC','BD'})
        self.assertEqual(data_reference_columns('SUM(BB:BC)'),{'BB','BC'})
        with self.assertRaisesRegex(ValueError,'Не поддерживается функция'):
            FormulaParser(formula,2).parse()
        with self.assertRaisesRegex(ValueError,'Слишком большой'):
            FormulaParser('SUM(BB2:BB50000)',2).parse()

    def test_strings_other_sheets_and_unknown_names_are_not_data_dependencies(self):
        self.assertEqual(data_reference_columns('IF(A2>0,"BB12",\'Поправки\'!$BB$2)'),{'A'})
        self.assertIsNone(data_reference_columns('SUMIF(BB2:BB9,">0",Table1[Amount])'))
        self.assertIsNone(data_reference_columns('BB2+MyNamedValue'))
        self.assertIsNone(data_reference_columns('"unterminated'))


class LegacySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'book.xlsx';fixture(self.path)
        book=load_workbook(self.path)
        for row in (2,3,4):book['Данные'][f'M{row}']=f'=84+H{row}*0'
        book.save(self.path)
        patcher=patch.object(wp,'profile_path',return_value=Path(self.temp.name)/'profiles.json')
        patcher.start();self.addCleanup(patcher.stop)

    def setup_book(self):
        layout=wp.read_layout(self.path)
        return layout,wp.confirm(layout,'station','1',wp.suggestions(layout,'station','1'),save=False)

    def panel(self):
        book=load_workbook(self.path);sheet=book['Данные']
        sheet['Q2']='=SUMIF($O$2:$O$50000,">0",$O$2:$O$50000)'
        sheet['Q3']='=Q2*2';sheet['Q4']='=Q3*2'
        sheet['R3']='=Q3+O3';sheet['R4']='=Q4+O4'
        # openpyxl emits no formula caches. A preserved numeric footer keeps
        # the blank-headed columns visible to the real calamine reader.
        sheet['S5']=0.
        book.save(self.path)

    def test_same_column_subtotal_does_not_become_a_false_cycle(self):
        self.panel();layout,setup=self.setup_book()
        self.assertEqual(layout.variants['Q'][1]['count'],2)
        self.assertNotIn('Q',setup.recipes)
        self.assertNotIn('R',setup.recipes)
        wp.validate_recalculation(setup)
        values=layout.values.iloc[:3].copy();values['Q']=[7.,14.,28.]
        setup.recalculate(values)
        np.testing.assert_allclose(values.I,[127.5,128.75,130.])
        self.assertEqual(values.Q.tolist(),[7.,14.,28.])

    def test_legitimate_helper_is_kept_even_with_a_secondary_old_total(self):
        self.panel();book=load_workbook(self.path);sheet=book['Данные']
        for row in (2,3):sheet[f'S{row}']=f'=H{row}/100'
        sheet['S4']='=SUMIF(O2:O50000,">0",O2:O50000)'
        for row in (2,3,4):sheet[f'I{row}']=f'=H{row}/S{row}'
        book.save(self.path);layout,setup=self.setup_book()
        self.assertIn('S',setup.recipes)
        wp.validate_recalculation(setup)
        values=layout.values.iloc[:3].copy();setup.recalculate(values)
        np.testing.assert_allclose(values.S,[1.02,1.03,1.04])
        np.testing.assert_allclose(values.I,100.)

    def test_required_dependency_on_excluded_old_losses_is_rejected(self):
        self.panel();book=load_workbook(self.path)
        for row in (2,3,4):book['Данные'][f'I{row}']=f'=H{row}/Q{row}'
        book.save(self.path);_,setup=self.setup_book()
        with self.assertRaisesRegex(ValueError,'Для новых строк нет формулы|неподдерживаемая формула'):
            wp.validate_recalculation(setup)

    def test_portable_profile_keeps_exclusion_and_required_helpers(self):
        self.panel();layout,setup=self.setup_book()
        values=layout.values.iloc[:3].copy();values['Q']=[7.,14.,28.]
        setup.recalculate(values)
        destination=Path(self.temp.name)/'portable.xlsx'
        save_result_workbook(AssembledData(values,layout.headers,0,0,{},[]),[],destination,
                             book_profile=setup.metadata())
        restored_layout=wp.read_layout(destination)
        restored=wp.confirm(restored_layout,'station','1',wp.suggestions(restored_layout,'station','1'),save=False)
        wp.validate_recalculation(restored)
        self.assertNotIn('Q',restored.recipes)
        self.assertNotIn('R',restored.recipes)
        actual=restored_layout.values.copy();restored.recalculate(actual)
        np.testing.assert_allclose(actual.I,[127.5,128.75,130.])
        self.assertEqual(actual.Q.tolist(),[7.,14.,28.])

    def test_genuine_helper_cycle_still_fails_with_readable_column(self):
        book=load_workbook(self.path)
        for row in (2,3,4):
            book['Данные'][f'Q{row}']=f'=R{row}+1'
            book['Данные'][f'R{row}']=f'=Q{row}+1'
            book['Данные'][f'I{row}']=f'=H{row}/Q{row}'
        book['Данные']['S5']=0.
        book.save(self.path);layout,setup=self.setup_book()
        values=layout.values.iloc[:3].copy();before=values.copy(deep=True)
        with self.assertRaisesRegex(ValueError,'Циклическая зависимость расчётной колонки [QR]') as error:
            setup.recalculate(values)
        self.assertNotIn('aux_',str(error.exception))
        pd.testing.assert_frame_equal(values,before)

    def test_direct_evaluator_cycles_keep_the_safety_check(self):
        recipes={'A':{'node':FormulaParser('A2+1',2).parse()}}
        evaluator=FormulaEvaluator(pd.DataFrame({'A':[1.,2.]}),recipes,{},labels={'A':'Вспомогательная A'})
        with self.assertRaisesRegex(ValueError,'Циклическая.*Вспомогательная A'):
            evaluator.column('A')
