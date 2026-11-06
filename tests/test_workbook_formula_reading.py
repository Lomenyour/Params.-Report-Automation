"""Shared Excel formulas retain the same variants as explicit cell formulas."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from openpyxl import Workbook
from openpyxl.formula.translate import Translator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
import workbook_profile as wp

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


class FormulaReadingTest(unittest.TestCase):
    def test_shared_rows_and_columns_match_explicit_mixed_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit, shared = root / 'explicit.xlsx', root / 'shared.xlsx'
            book = Workbook()
            sheet = book.active
            sheet.title = 'Данные'
            sheet.append(['Дата', 'Тнк, °С', 'ВНА', 'Расчёт 1', 'Расчёт 2', 'Расчёт 3'])
            formula = 'IF(B2>0,B2+$B2+B$2+$B$2+SUM(B2:C2)+\'Коэфф A1\'!$A$1,0)'
            translator = Translator('=' + formula, origin='D2')
            for row in range(2, 10):
                sheet.append([pd.Timestamp('2026-01-01') + pd.Timedelta(minutes=30*(row-2)), 20., 86.])
                for col in 'DEF':
                    sheet[f'{col}{row}'] = translator.translate_formula(f'{col}{row}')
            book.create_sheet('Коэфф A1')['A1'] = .5
            book.save(explicit)
            with ZipFile(explicit) as source, ZipFile(shared, 'w') as target:
                for name in source.namelist():
                    content = source.read(name)
                    if name == 'xl/worksheets/sheet1.xml':
                        tree = ET.fromstring(content)
                        for cell in tree.iter(NS + 'c'):
                            node = cell.find(NS + 'f')
                            if node is None:
                                continue
                            node.set('t', 'shared')
                            node.set('si', '0')
                            if cell.attrib['r'] == 'D2':
                                node.set('ref', 'D2:F9')
                            else:
                                node.text = None
                        content = ET.tostring(tree)
                    target.writestr(name, content)
            expected = wp.read_layout(explicit)
            with patch.object(wp, 'Translator', wraps=Translator) as translate:
                actual = wp.read_layout(shared)
            self.assertEqual(translate.call_count, 1)
            self.assertEqual(actual.headers, expected.headers)
            self.assertEqual(actual.variants, expected.variants)
            self.assertEqual(actual.constants, expected.constants)
            self.assertEqual(actual.formula_error, expected.formula_error)
            pd.testing.assert_frame_equal(actual.values, expected.values)
            # Returned values/metadata remain isolated from the cached layout.
            actual.values.iloc[0, 1] = 123.
            actual.variants['D'][0]['count'] = 999
            cached = wp.read_layout(shared)
            self.assertEqual(cached.variants, expected.variants)
            pd.testing.assert_frame_equal(cached.values, expected.values)


if __name__ == '__main__':
    unittest.main()
