# -*- coding: utf-8 -*-
"""Центральный запуск расчётов.

Здесь живёт ПУТЬ К КНИГЕ С ДАННЫМИ — его получают оба расчёта,
VNA_full и RH_raschet, аргументами `--file` и `--sheet`.
Чтобы посчитать другую книгу, менять нужно только здесь.

Каждый скрипт запускается ОТДЕЛЬНЫМ процессом: так они не мешают друг
другу — свои глобальные переменные, свой вывод, свои графики, падение
одного не тянет второй.

ЗАПУСК:
    py scr/raschet.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows-консоль по умолчанию работает в cp1251 и падает на некоторых
# символах. Заменяем невыводимые символы, чтобы лог не ронял скрипт.
# line_buffering=True — иначе при перенаправлении вывода строки нашего
# лога и строки дочерних процессов перемешиваются.
try:
    sys.stdout.reconfigure(errors="replace", line_buffering=True)
    sys.stderr.reconfigure(errors="replace", line_buffering=True)
except AttributeError:
    pass


ROOT = Path(__file__).resolve().parents[1]
SCR_DIR = ROOT / "scr"


# ============================================================
# КНИГА С ДАННЫМИ — единственное место, где она задаётся
# ============================================================

INPUT_FILE = "СызТЭЦ ГТ-11 2кв 2026.xlsm"
SHEET_NAME = "Данные"


# ============================================================
# ЧТО ЗАПУСКАЕМ
# ============================================================

SCRIPTS = [
    ("VNA_full.py", "Расчёт ВНА (КПД компрессора)"),
    ("RH_raschet.py", "Расчёт расходной характеристики"),
]

LINE = "#" * 78


def run_script(name: str, title: str, data_file: Path) -> int:
    script = SCR_DIR / name

    print()
    print(LINE)
    print(f"### {title}")
    print(f"### {script.name}")
    print(f"### данные: {data_file.name}, лист '{SHEET_NAME}'")
    print(LINE)

    if not script.exists():
        print(f"!!! Файл не найден: {script}")
        return 1

    if not data_file.exists():
        print(f"!!! Книга не найдена: {data_file}")
        return 1

    result = subprocess.run([
        sys.executable,
        str(script),
        "--file", str(data_file),
        "--sheet", SHEET_NAME,
    ])

    print()
    if result.returncode == 0:
        print(f"--- {name}: готово")
    else:
        print(f"!!! {name}: код возврата {result.returncode}")

    return result.returncode


def main() -> int:
    data_file = ROOT / "data" / INPUT_FILE

    print()
    print(f"Книга с данными: {data_file}")
    print(f"Лист: {SHEET_NAME}")

    failed = []

    for name, title in SCRIPTS:
        if run_script(name, title, data_file) != 0:
            failed.append(name)

    print()
    print("=" * 78)
    if failed:
        print("ЗАВЕРШЕНО С ОШИБКАМИ:")
        for name in failed:
            print(f"  - {name}")
        return 1

    print("ВСЁ ГОТОВО: оба расчёта отработали.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
