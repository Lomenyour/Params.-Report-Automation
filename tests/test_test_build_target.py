"""An old package name must fail before a second test directory is created."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SingleTestPackageTest(unittest.TestCase):
    def test_legacy_name_is_rejected_before_build_side_effects(self):
        source = Path(__file__).resolve().parents[1] / 'build_gui.ps1'
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / source.name
            shutil.copy2(source, script)
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(script), '-Name', 'GTU_Report_Desktop_Test'],
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('GTU_Report_Rotor_Test', result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [script])
