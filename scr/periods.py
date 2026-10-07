# -*- coding: utf-8 -*-
"""Определение периодов работы ГТУ — общая логика.

Вынесено отдельным модулем, потому что разбивка на периоды нужна сразу
двум расчётам:

  - `RH_raschet.py` ищет пары окон ВНУТРИ каждого периода;
  - `VNA_full.py` считает КПД компрессора тоже ПО КАЖДОМУ периоду.

Если держать два независимых определения, они разъедутся: один скрипт
будет считать периоды по автоопределению, второй — по ручному списку.

Путь к книге здесь НЕ зашит: его задаёт `raschet.py` и передаёт скриптам.
"""
from __future__ import annotations

import pandas as pd


# ============================================================
# НАСТРОЙКИ ОПРЕДЕЛЕНИЯ ПЕРИОДОВ
# ============================================================

# Мощность, ниже которой ГТУ считаем неработающей
LOW_POWER = 10

# Порог «долгого останова»: сколько записей подряд с мощностью <= LOW_POWER
# считать остановом ГТУ. 6 суток × 48 записей/сутки.
#
# Проверено на двух книгах:
#
#   СызТЭЦ: простои 3.5, 5.0, 5.6, 6.5, 9.6, 14.8, 37.8 сут;
#           паузы внутри работы — 1.5 и 1.8 сут. 4 периода при 2..6 сут.
#   НКТЭЦ:  мелкие остановы 2.3 .. 4.3 сут (за периоды их считать не надо),
#           реальные 11.5, 11.9, 12.1, 33.5 сут.
#           При 5..7 сут — 3 периода, при 4 сут уже 4, при 3 сут — 7.
#
# Пересечение: 5 или 6 суток дают правильную разбивку на обеих книгах.
# Взято 6 — и у НКТЭЦ запас до мелких остановов (4.3 сут) больше.
GAP_SIZE = 6 * 48

# Сколько записей подряд должно быть на мощности, чтобы считать,
# что ГТУ действительно вышла из останова. 24 часа = 48 записей.
WORK_CONFIRM_SIZE = 48


# ============================================================
# РУЧНАЯ ПРАВКА ПЕРИОДОВ
#
# Пустой список = периоды определяются автоматически (по GAP_SIZE).
#
# Если автоматика разбила неверно — в логе печатается готовый блок
# с найденными периодами: скопируй его сюда вместо строки
# `PERIOD_OVERRIDES = []` и убери или поправь лишние периоды.
#
# Формат даты: "дд-мм-гггг чч:мм" либо "дд-мм-гггг".
#
# Пример — из четырёх найденных периодов оставить два:
#
# PERIOD_OVERRIDES = [
#     ("11-12-2024 14:00", "01-06-2025 00:30"),   # 1
#     ("13-06-2025 08:30", "01-11-2025 00:30"),   # 2
# ]
# ============================================================

PERIOD_OVERRIDES: list[tuple[str, str]] = []


# ============================================================
# ОПРЕДЕЛЕНИЕ ПЕРИОДОВ
# ============================================================

def detect_periods(df):
    """Размечает периоды работы ГТУ автоматически, по GAP_SIZE."""

    # Индекс сбрасываем: ниже строки адресуются позиционно (df.loc[i]),
    # а у вызывающей стороны индекс может быть с дырками — например,
    # в VNA_full после dropna. Без сброса падает с KeyError.
    df = df.reset_index(drop=True).copy()
    df["period"] = 0

    current_period = 1
    low_power_count = 0
    in_long_stop = False
    i = 0

    while i < len(df):
        power = df.loc[i, "power"]

        if pd.isna(power):
            i += 1
            continue

        if power <= LOW_POWER:
            low_power_count += 1

            if low_power_count >= GAP_SIZE:
                in_long_stop = True

            i += 1
            continue

        if not in_long_stop:
            df.loc[i, "period"] = current_period
            low_power_count = 0
            i += 1
            continue

        candidate_start = i
        confirmed = True

        check_end = min(i + WORK_CONFIRM_SIZE, len(df))

        for j in range(i, check_end):
            p = df.loc[j, "power"]

            if pd.isna(p):
                continue

            if p <= LOW_POWER:
                confirmed = False
                break

        if confirmed and (check_end - i) >= WORK_CONFIRM_SIZE:
            current_period += 1
            df.loc[candidate_start, "period"] = current_period

            for j in range(candidate_start + 1, check_end):
                p = df.loc[j, "power"]

                if pd.isna(p):
                    continue

                if p > LOW_POWER:
                    df.loc[j, "period"] = current_period

            in_long_stop = False
            low_power_count = 0
            i = check_end
        else:
            i = candidate_start + 1

    return df


def apply_period_overrides(df, overrides):
    """Размечает периоды по списку, заданному в PERIOD_OVERRIDES.

    Нужна, когда автоматическое определение по GAP_SIZE разбило данные
    неверно (например, мелкий останов посчитало концом периода).

    Перекрывающиеся интервалы не суммируются: строка попадает в тот
    период, который в списке идёт раньше.
    """

    result = df.copy()
    result["period"] = 0

    for number, (raw_start, raw_end) in enumerate(overrides, start=1):

        try:
            start = pd.to_datetime(raw_start, dayfirst=True)
            end = pd.to_datetime(raw_end, dayfirst=True)
        except Exception as error:
            raise ValueError(
                f"Не разобрать даты периода {number}: "
                f"{raw_start!r} .. {raw_end!r} ({error})"
            ) from error

        if start > end:
            raise ValueError(
                f"Период {number}: начало ({raw_start}) позже конца ({raw_end})"
            )

        mask = (
            (result["date"] >= start)
            & (result["date"] <= end)
            & (result["period"] == 0)
        )

        result.loc[mask, "period"] = number

    return result


def describe_periods(df):
    """Сводка по размеченным периодам: начало, конец, длительность, записей."""

    rows = []

    work_df = df[(df["period"] > 0) & (df["power"] > LOW_POWER)]

    for period_number, period_df in work_df.groupby("period"):
        period_df = period_df.sort_values("date")

        date_start = period_df["date"].iloc[0]
        date_end = period_df["date"].iloc[-1]
        duration_days = (date_end - date_start).total_seconds() / 86400

        rows.append({
            "period": period_number,
            "date_start": date_start,
            "date_end": date_end,
            "duration_days": duration_days,
            "records": len(period_df),
        })

    return pd.DataFrame(rows)


def build_periods(df):
    """Единая точка входа: размеченный df + сводка по периодам.

    Если PERIOD_OVERRIDES непустой — автоопределение отключается.
    """

    if PERIOD_OVERRIDES:
        marked = apply_period_overrides(df, PERIOD_OVERRIDES)
    else:
        marked = detect_periods(df)

    return marked, describe_periods(marked)


def print_period_overrides_template(periods_df, used_overrides):
    """Печатает готовый блок PERIOD_OVERRIDES для копирования в настройки."""

    if periods_df.empty:
        return

    print()
    print("-" * 70)

    if used_overrides:
        print("Периоды взяты из PERIOD_OVERRIDES (автоопределение отключено).")
    else:
        print("Периоды определены автоматически (GAP_SIZE).")

    print("Если разбивка неверная — скопируй блок ниже в scr/periods.py")
    print("вместо строки  PERIOD_OVERRIDES = []")
    print("и убери или поправь лишние периоды.")
    print("-" * 70)
    print()
    print("PERIOD_OVERRIDES = [")

    for row in periods_df.itertuples(index=False):

        print(
            f'    ("{row.date_start:%d-%m-%Y %H:%M}", '
            f'"{row.date_end:%d-%m-%Y %H:%M}"),'
            f'   # {int(row.period)}'
        )

    print("]")
