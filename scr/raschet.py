# -*- coding: utf-8 -*-
"""Центральный запуск расчётов.

Здесь живёт ПУТЬ К КНИГЕ С ДАННЫМИ (INPUT_FILE, SHEET_NAME) — его
получают оба расчёта аргументами --file и --sheet. Чтобы посчитать
другую книгу, менять нужно только здесь.

Порядок работы:
  1) показываем авторазметку периодов (таблица + график) — без расчёта;
  2) спрашиваем в консоли: ок или нет;
  3) если «нет» — вводим периоды вручную: дата1;дата2, по одному на строку;
  4) запускаем VNA_full и RH_raschet, каждый отдельным процессом.

ЗАПУСК:
    py scr/raschet.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows-консоль по умолчанию работает в cp1251 и падает на некоторых
# символах. Заменяем невыводимые символы, чтобы лог не ронял скрипт.
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

YES = {"", "ок", "да", "yes", "y"}
NO = {"нет", "no", "n"}


def run_script(name: str, title: str, data_file: Path, extra: list[str] | None = None) -> int:
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

    command = [
        sys.executable,
        str(script),
        "--file", str(data_file),
        "--sheet", SHEET_NAME,
    ]
    if extra:
        command.extend(extra)

    result = subprocess.run(command)

    print()
    if result.returncode == 0:
        print(f"--- {name}: готово")
    else:
        print(f"!!! {name}: код возврата {result.returncode}")

    return result.returncode


def ask_periods() -> list[tuple[str, str]] | None:
    """Спрашивает, ок ли разметка.

    Возвращает список (start, end), если пользователь ввёл свои периоды,
    либо None, если согласен с автоопределением.
    """

    while True:
        print()
        try:
            answer = input(
                "Периоды ок?  (ок/да/yes — едем дальше;  нет/no — правим): "
            ).strip().lower()
        except EOFError:
            # запуск без терминала — считаем, что всё ок, едем дальше
            return None

        if answer in YES:
            return None

        if answer not in NO:
            print("  Не понял ответ — напиши 'ок' или 'нет'.")
            continue

        print()
        print("Введи периоды: по одному на строку, формат  дата1;дата2")
        print("  пример: 11-12-2024 14:00;01-06-2025 00:30")
        print("Пустая строка — закончить ввод.")
        print()

        periods: list[tuple[str, str]] = []

        while True:
            try:
                line = input().strip()
            except EOFError:
                line = ""

            if not line:
                break

            if ";" not in line:
                print(f"  пропущено (нет ';'): {line}")
                continue

            start, end = [part.strip() for part in line.split(";", 1)]
            periods.append((start, end))
            print(f"  + период {len(periods)}: {start} ; {end}")

        if periods:
            return periods

        print("  Не введено ни одного периода — повторяю вопрос.")


def encode_periods(periods: list[tuple[str, str]]) -> str:
    """Сворачивает периоды в строку для аргумента --periods."""
    return "|".join(f"{start};{end}" for start, end in periods)


def main() -> int:
    data_file = ROOT / "data" / INPUT_FILE

    print()
    print(f"Книга с данными: {data_file}")
    print(f"Лист: {SHEET_NAME}")

    # 1) предпросмотр разметки периодов (таблица + график), без расчёта
    run_script(
        "RH_raschet.py",
        "Разметка периодов (предпросмотр)",
        data_file,
        extra=["--periods-only"],
    )

    # 2) спрашиваем пользователя
    periods = ask_periods()

    extra: list[str] = []

    if periods:
        extra = ["--periods", encode_periods(periods)]
        print()
        print(f"Используем {len(periods)} периодов вручную.")

    # 3) расчёты
    failed = []

    for name, title in SCRIPTS:
        if run_script(name, title, data_file, extra=extra) != 0:
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
