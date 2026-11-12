from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from package_check import check_word_report


class PackageWordCheckTest(unittest.TestCase):
    def test_check_uses_standard_generator_and_rejects_unresolved_tags(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);template=root/'template.docx';template.write_bytes(b'template')
            source=root/'context.json';source.write_text('{}')
            output=root/'report.docx';status=root/'status.json'
            def render(*args,**kwargs):
                with ZipFile(output,'w') as file:file.writestr('word/document.xml','<document>OK</document>')
            with patch('reporting.DEFAULT_TEMPLATE',template),patch('reporting.generate_report_from_json',side_effect=render) as generator:
                self.assertEqual(check_word_report([str(source),str(output),str(status)]),0)
                generator.assert_called_once_with(source.resolve(),template_path=template,output_path=output.resolve())
                self.assertTrue(json.loads(status.read_text(encoding='utf-8'))['ok'])
            def invalid(*args,**kwargs):
                with ZipFile(output,'w') as file:file.writestr('word/document.xml','{{ missing }}')
            with patch('reporting.DEFAULT_TEMPLATE',template),patch('reporting.generate_report_from_json',side_effect=invalid):
                self.assertEqual(check_word_report([str(source),str(output),str(status)]),1)
                self.assertIn('остались теги',json.loads(status.read_text(encoding='utf-8'))['error'])

    def test_invalid_arguments_and_template_overwrite_are_rejected(self):
        self.assertEqual(check_word_report([]),2)
        self.assertEqual(check_word_report(['a','a','status.json']),2)
        with TemporaryDirectory() as folder:
            root=Path(folder);template=root/'template.docx';template.write_bytes(b'unchanged')
            with patch('reporting.DEFAULT_TEMPLATE',template):
                self.assertEqual(check_word_report([str(root/'context.json'),str(template),str(root/'status.json')]),1)
            self.assertEqual(template.read_bytes(),b'unchanged')
