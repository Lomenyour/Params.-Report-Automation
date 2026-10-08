"""Запуск GUI двойным щелчком через pythonw.exe."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scr"))
runpy.run_path(str(ROOT / "scr" / "app.py"), run_name="__main__")
