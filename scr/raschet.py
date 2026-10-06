# -*- coding: utf-8 -*-
"""Запуск обоих расчётов подряд: сначала ВНА, затем расходная характеристика.

Каждый скрипт запускается ОТДЕЛЬНЫМ процессом. Так они не мешают друг
другу: у каждого свои глобальные переменные, свой вывод и свои графики,
и падение одного не тянет за собой второй.

ЗАПУСК:
    py src/raschet.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows-консоль по умолчанию работает в cp1251 и падает на некоторых
# символах. Заменяем невыводимые символы, чтобы лог не ронял скрипт.
#
# line_buffering=True — иначе при перенаправлении вывода в файл строки
# нашего лога и строки дочерних процессов перемешиваются.
try:
    sys.stdout.reconfigure(errors="replace", line_buffering=True)
    sys.stderr.reconfigure(errors="replace", line_buffering=True)
except AttributeError:
    pass


SCR_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    ("VNA_full.py", "Расчёт ВНА (КПД компрессора)"),
    ("RH_raschet.py", "Расчёт расходной характеристики"),
]

LINE = "#" * 78


def run_script(name: str, title: str) -> int:
    script = SCR_DIR / name

    print()
    print(LINE)
    print(f"### {title}")
    print(f"### {script}")
    print(LINE)

    if not script.exists():
        print(f"!!! Файл не найден: {script}")
        return 1

    result = subprocess.run([sys.executable, str(script)])

    print()
    if result.returncode == 0:
        print(f"--- {name}: готово")
    else:
        print(f"!!! {name}: код возврата {result.returncode}")

    return result.returncode


def main() -> int:
    failed = []

    for name, title in SCRIPTS:
        if run_script(name, title) != 0:
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
