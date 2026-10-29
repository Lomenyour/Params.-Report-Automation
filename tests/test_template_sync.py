"""Template synchronization must preserve edits and reject ambiguous overwrites."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class TemplateSyncTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        script = Path(__file__).resolve().parents[1] / 'sync_report_templates.ps1'
        shutil.copy2(script,self.root/script.name)
        self.source = self.root/'word_auto/templates/template_mapped.docx'
        self.target = self.root/'dist_test/GTU_Report_Desktop_Test/word_auto/templates/template_mapped.docx'
        for path in (self.source,self.target):
            path.parent.mkdir(parents=True,exist_ok=True)

    def run_sync(self,*args):
        return subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(self.root/'sync_report_templates.ps1'),*args],capture_output=True,text=True)

    def test_explicit_test_choice_preserves_previous_source(self):
        self.source.write_bytes(b'old-source')
        self.target.write_bytes(b'approved-test')
        result = self.run_sync('-Prefer','Test')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.source.read_bytes(),b'approved-test')
        backups = list((self.root/'archive_builds').rglob('*.docx'))
        self.assertEqual([p.read_bytes() for p in backups],[b'old-source'])

    def test_one_sided_changes_sync_both_directions(self):
        self.source.write_bytes(b'base')
        self.target.write_bytes(b'base')
        self.assertEqual(self.run_sync().returncode,0)
        self.target.write_bytes(b'test-edited')
        self.assertEqual(self.run_sync().returncode,0)
        self.assertEqual(self.source.read_bytes(),b'test-edited')
        self.source.write_bytes(b'source-edited')
        self.assertEqual(self.run_sync().returncode,0)
        self.assertEqual(self.target.read_bytes(),b'source-edited')

    def test_two_sided_changes_are_not_overwritten(self):
        self.source.write_bytes(b'base')
        self.target.write_bytes(b'base')
        self.assertEqual(self.run_sync().returncode,0)
        self.source.write_bytes(b'source-change')
        self.target.write_bytes(b'test-change')
        result = self.run_sync()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Template conflict',result.stderr)
        self.assertEqual(self.source.read_bytes(),b'source-change')
        self.assertEqual(self.target.read_bytes(),b'test-change')

    def test_unknown_initial_difference_requires_explicit_choice(self):
        self.source.write_bytes(b'source')
        self.target.write_bytes(b'test')
        self.assertNotEqual(self.run_sync().returncode,0)
        self.assertEqual(self.source.read_bytes(),b'source')
        self.assertEqual(self.target.read_bytes(),b'test')

    def test_invalid_name_cannot_escape_workspace(self):
        self.assertNotEqual(self.run_sync('-TestName','../outside').returncode,0)
        self.assertFalse((self.root/'build_test').exists())


if __name__ == '__main__':
    unittest.main()
