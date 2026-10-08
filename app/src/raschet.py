# -*- coding: utf-8 -*-
"""Центральный запуск расчётов.

Здесь живёт ПУТЬ К КНИГЕ С ДАННЫМИ (INPUT_FILE, SHEET_NAME) — его
получают оба расчёта аргументами --file и --sheet. Чтобы посчитать
другую книгу, менять нужно только здесь.

Порядок работы:
  1) показываем авторазметку периодов (таблица + график) — без расчёта;
  2) спрашиваем в консоли: ок или нет;
  3) если «нет» — вводим периоды вручную: дата1;дата2, по одному на строку;
  4) запускаем VNA_full и RH_raschet в одном процессе на общих данных.

ЗАПУСК:
    py scr/raschet.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import periods as periods_mod
from data_loader import load_source_data, prepare_rh_data, prepare_vna_data
from RH_raschet import main as run_rh
from VNA_full import main as run_vna

# Windows-консоль по умолчанию работает в cp1251 и падает на некоторых
# символах. Заменяем невыводимые символы, чтобы лог не ронял скрипт.
try:
    sys.stdout.reconfigure(errors="replace", line_buffering=True)
    sys.stderr.reconfigure(errors="replace", line_buffering=True)
except AttributeError:
    pass


ROOT = Path(__file__).resolve().parents[1]
# ============================================================
# КНИГА С ДАННЫМИ — единственное место, где она задаётся
# ============================================================

INPUT_FILE = "СызТЭЦ ГТ-11 2кв 2026.xlsm"
SHEET_NAME = "Данные"


LINE = "#" * 78

YES = {"", "ок", "да", "yes", "y"}
NO = {"нет", "no", "n"}


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


def main() -> int:
    data_file = ROOT / "data" / INPUT_FILE

    print()
    print(f"Книга с данными: {data_file}")
    print(f"Лист: {SHEET_NAME}")

    if not data_file.exists():
        print(f"!!! Книга не найдена: {data_file}")
        return 1

    try:
        # Книга открывается один раз. Оба расчёта используют эти данные.
        source = load_source_data(data_file, SHEET_NAME)
        rh_data = prepare_rh_data(source)
        vna_data = prepare_vna_data(source)

        # 1) предпросмотр разметки периодов
        print()
        print(LINE)
        print("### Разметка периодов (предпросмотр)")
        print(LINE)
        run_rh(rh_data, periods_only=True, show_plots=True)

        # 2) подтверждение или ручной ввод периодов
        periods = ask_periods()
        if periods:
            periods_mod.PERIOD_OVERRIDES = periods
            print()
            print(f"Используем {len(periods)} периодов вручную.")

        # 3) расчёты в одном процессе на уже загруженных данных
        print()
        print(LINE)
        print("### Расчёт ВНА (КПД компрессора)")
        print(LINE)
        vna_df, _, _, _ = run_vna(data=vna_data)

        print()
        print(LINE)
        print("### Расчёт расходной характеристики")
        print(LINE)
        run_rh(
            rh_data,
            periods_only=False,
            show_plots=True,
            vna_data=vna_df,
        )

    except Exception as error:
        print()
        print(f"!!! Расчёт завершён с ошибкой: {error}")
        return 1

    print()
    print("=" * 78)
    print("ВСЁ ГОТОВО: оба расчёта отработали.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
