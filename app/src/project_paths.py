"""Общие пути результатов для запуска из исходников и собранного EXE."""
from __future__ import annotations

from pathlib import Path
import sys


def output_directory() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1] / "data" / "output"
    executable_dir = Path(sys.executable).resolve().parent
    for candidate in (executable_dir, *executable_dir.parents):
        if (candidate / "scr" / "app.py").is_file():
            return candidate / "data" / "output"
    return executable_dir / "data" / "output"


OUTPUT_DIR = output_directory()
