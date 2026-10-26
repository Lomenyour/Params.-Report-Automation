import heapq
import re
import sys

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

from CoolProp.CoolProp import PropsSI

# Разбивка на периоды — общая логика, живёт в scr/periods.py.
import periods as periods_mod
from periods import (
    build_periods,
    make_periods_display_table,
    parse_periods_arg,
    print_period_overrides_template,
)
from data_loader import load_source_data, prepare_vna_data


# Windows-консоль по умолчанию работает в cp1251 и падает на символах
# вроде 'φ' из заголовков Excel. Заменяем невыводимые символы,
# чтобы лог не ронял скрипт.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except AttributeError:
    pass


# ============================================================
# НАСТРОЙКИ
# ============================================================

# ============================================================
# КНИГА С ДАННЫМИ ПРИХОДИТ АРГУМЕНТОМ
#
# Книгу задаёт ЕДИНСТВЕННОЕ место — центральный scr/raschet.py:
#     python scr/VNA_full.py --file "data\книга.xlsx" --sheet "Данные"
#
# Своего файла по умолчанию здесь НЕТ намеренно: иначе VNA_full
# и RH_raschet могли бы молча посчитать разные книги за один прогон.
# ============================================================

FILE_NAME = None

# Правило 0.2: читаем только первый лист — "Данные"
SHEET_NAME = "Данные"


def apply_cli_overrides():
    global FILE_NAME, SHEET_NAME

    arguments = sys.argv[1:]

    for index, argument in enumerate(arguments):
        if index + 1 >= len(arguments):
            continue
        if argument == "--file":
            FILE_NAME = Path(arguments[index + 1])
        elif argument == "--sheet":
            SHEET_NAME = arguments[index + 1]
        elif argument == "--periods":
            periods_mod.PERIOD_OVERRIDES = parse_periods_arg(arguments[index + 1])

    if FILE_NAME is None:
        raise SystemExit(
            "Не задана книга с данными.\n"
            "Запускай расчёт через центральный скрипт:\n"
            "    py scr/raschet.py\n"
            "либо передай путь явно:\n"
            "    py scr/VNA_full.py --file \"data\\книга.xlsx\""
        )


MAX_DELTA_T = 0.5      # °C
MAX_DELTA_P = 5.0      # мбар = 500 Па

# Поиск интервалов ВНА выполняется по сетке 0,1°. Ширина интервала
# меняется от 0,1° до 1,0°. Гистограмма ниже остаётся с шагом 1°:
# она нужна как обзор распределения и не участвует в выборе TOP-10.
VNA_INTERVAL_STEP = 0.1
VNA_MIN_INTERVAL_WIDTH = 0.1
VNA_MAX_INTERVAL_WIDTH = 1.0
MAX_DELTA_ETA = 0.8    # п.п.; в TOP-10 проходят только delta_eta < 0.8

TOP_INTERVALS = 10


# ============================================================
# ФУНКЦИЯ РАСЧЕТА КПД КОМПРЕССОРА
# ============================================================

def calculate_compressor_efficiency(t, p, tkk, pkk):
    """
    Расчет изоэнтропического КПД компрессора.

    t   - температура на входе, °C
    p   - давление на входе, мбар
    tkk - температура на выходе, °C
    pkk - давление на выходе, бар

    Возвращает:
    eta - КПД, %
    h1  - энтальпия на входе, кДж/кг
    h2  - реальная энтальпия на выходе, кДж/кг
    h2s - изоэнтропическая энтальпия на выходе, кДж/кг
    """

    # --------------------------------------------------------
    # Перевод единиц
    # --------------------------------------------------------

    T1 = t + 273.15
    P1 = p * 100

    T2 = tkk + 273.15
    P2 = pkk * 1e5

    # --------------------------------------------------------
    # Проверка точки на физическую корректность
    #
    # В данных есть строки останова и переходных режимов:
    # отрицательные давления, нулевые, либо давление на выходе
    # НЕ выше входного (машина не сжимает). На таких точках CoolProp
    # падает или КПД выходит бессмысленным (например, −2167 %).
    # Такие точки помечаем NaN.
    # --------------------------------------------------------

    if P1 <= 0 or P2 <= P1:

        return np.nan, np.nan, np.nan, np.nan

    # --------------------------------------------------------
    # Опорная энтальпия
    # --------------------------------------------------------

    h0 = PropsSI(
        "H",
        "T", 273.15,
        "P", 101325,
        "HEOS::Air"
    )

    # --------------------------------------------------------
    # Энтальпия на входе
    # --------------------------------------------------------

    h1 = (
        PropsSI(
            "H",
            "T", T1,
            "P", P1,
            "HEOS::Air"
        )
        - h0
    ) / 1000

    # --------------------------------------------------------
    # Энтальпия на выходе реальная
    # --------------------------------------------------------

    h2 = (
        PropsSI(
            "H",
            "T", T2,
            "P", P2,
            "HEOS::Air"
        )
        - h0
    ) / 1000

    # --------------------------------------------------------
    # Энтропия на входе
    # --------------------------------------------------------

    s1 = PropsSI(
        "S",
        "T", T1,
        "P", P1,
        "HEOS::Air"
    )

    # --------------------------------------------------------
    # Изоэнтропическая энтальпия на выходе
    # --------------------------------------------------------

    h2s = (
        PropsSI(
            "H",
            "S", s1,
            "P", P2,
            "HEOS::Air"
        )
        - h0
    ) / 1000

    # --------------------------------------------------------
    # КПД
    # --------------------------------------------------------

    denominator = h2 - h1

    if denominator == 0:
        return np.nan, h1, h2, h2s

    eta = (
        (h2s - h1)
        /
        denominator
        *
        100
    )

    return eta, h1, h2, h2s


def calculate_gtu_efficiency(power, fuel, gas_temperature, gas_pressure, q_lower):
    """Считает КПД ГТУ по формуле из книги Excel.

    power       — Nприв, МВт;
    fuel        — Bприв, нм³/ч;
    gas_temperature — температура газа, °C;
    gas_pressure — давление газа, МПа;
    q_lower     — Qнр, МДж/нм³.

    Энтальпия топлива рассчитывается для метана, как в текущей формуле книги:
    PropsSI("H", "T", Tгаз + 273.15, "P", Pгаз * 10^6, "HEOS::Methane").
    Ошибки и нулевой знаменатель повторяют поведение ЕСЛИОШИБКА(...;0).

    TODO: уточнить, должна ли формула Excel использовать только пару
    0.9631/Methane или полный состав топливного газа из листа «Результаты».
    Если нужен полный состав, его надо передавать в CoolProp как смесь,
    предварительно проверив единицы и нормировку долей.
    """

    values = [power, fuel, gas_temperature, gas_pressure, q_lower]
    if any(pd.isna(value) for value in values):
        return 0.0

    try:
        power = float(power)
        fuel = float(fuel)
        gas_temperature = float(gas_temperature)
        gas_pressure = float(gas_pressure)
        q_lower = float(q_lower)

        enthalpy = PropsSI(
            "H",
            "T", gas_temperature + 273.15,
            "P", gas_pressure * 1e6,
            "HEOS::Methane",
        ) / 1000.0

        denominator = fuel * q_lower / 3600.0 + enthalpy / 1000.0
        if not np.isfinite(denominator) or denominator == 0:
            return 0.0

        eta = power * 100.0 / denominator
        return float(eta) if np.isfinite(eta) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def add_gtu_efficiency(data):
    """Добавляет рассчитанный КПД ГТУ к строкам ВНА."""

    result = data.copy()
    result["eta_gtu"] = [
        calculate_gtu_efficiency(
            row.power,
            row.fuel,
            getattr(row, "gas_temperature", np.nan),
            getattr(row, "gas_pressure", np.nan),
            getattr(row, "q_lower", np.nan),
        )
        for row in result.itertuples(index=False)
    ]
    return result


# ============================================================
# ЗАГРУЗКА И ЗАПУСК РАСЧЁТА
# ============================================================

def load_data(file_path, sheet_name="Данные"):
    """Загружает и подготавливает данные ВНА через общий загрузчик."""
    return prepare_vna_data(load_source_data(file_path, sheet_name))


def run_vna(data, show_plots=True):
    """Считает ВНА по уже загруженному DataFrame."""
    data = add_gtu_efficiency(data)
    df, periods_df = build_periods(data)

    print()
    print("=" * 80)
    print("ПЕРИОДЫ РАБОТЫ ГТУ")
    print("=" * 80)

    if periods_df.empty:
        print("  Периоды не найдены.")
    else:
        print(make_periods_display_table(periods_df).to_string(index=False))

    print("=" * 80)
    print_period_overrides_template(periods_df, periods_mod.PERIOD_OVERRIDES)

    results = []
    figures = []
    for row in periods_df.itertuples(index=False):
        period_number = int(row.period)
        period_df = df[df["period"] == period_number].copy()
        if period_df.empty:
            print(f"Период {period_number}: нет данных — пропуск.")
            continue
        result_df, figure = analyze_period(
            period_df,
            period_number,
            show_plot=show_plots,
        )
        if figure is not None:
            figures.append(figure)
        if result_df is not None and not result_df.empty:
            result_df.attrs["period_number"] = period_number
            results.append(result_df)

    return df, periods_df, results, figures


def _build_pair_result(interval_df, dates, temperatures, pressures,
                       vna_values, tkk_values, pkk_values, pi_k_values, i, j):
    """Формирует результат для уже найденной допустимой пары точек."""

    date1 = pd.Timestamp(dates[i])
    date2 = pd.Timestamp(dates[j])

    t1 = temperatures[i]
    p1 = pressures[i]
    vna1 = vna_values[i]
    tkk1 = tkk_values[i]
    pkk1 = pkk_values[i]
    pi_k1 = pi_k_values[i]

    t2 = temperatures[j]
    p2 = pressures[j]
    vna2 = vna_values[j]
    tkk2 = tkk_values[j]
    pkk2 = pkk_values[j]
    pi_k2 = pi_k_values[j]

    delta_t = abs(t2 - t1)
    delta_p = abs(p2 - p1)
    delta_days = (date2 - date1).total_seconds() / 86400

    eta1, h1_1, h2_1, h2s_1 = calculate_compressor_efficiency(
        t1, p1, tkk1, pkk1
    )
    eta2, h1_2, h2_2, h2s_2 = calculate_compressor_efficiency(
        t2, p2, tkk2, pkk2
    )

    return {
        "date_1": date1,
        "t_1": t1,
        "p_1": p1,
        "vna_1": vna1,
        "tkk_1": tkk1,
        "pi_k_1": pi_k1,
        "eta_1": eta1,
        "h1_1": h1_1,
        "h2_1": h2_1,
        "h2s_1": h2s_1,
        "date_2": date2,
        "t_2": t2,
        "p_2": p2,
        "vna_2": vna2,
        "tkk_2": tkk2,
        "pi_k_2": pi_k2,
        "eta_2": eta2,
        "h1_2": h1_2,
        "h2_2": h2_2,
        "h2s_2": h2s_2,
        "delta_t": delta_t,
        "delta_p": delta_p,
        "delta_days": delta_days,
        "delta_eta": abs(eta2 - eta1),
    }


def _find_flexible_vna_intervals(df):
    """Находит пары для всех окон ВНА на сетке 0,1°.

    Окна имеют ширину от 0,1° до 1,0°. Для каждого окна сохраняется
    наиболее удалённая по времени допустимая пара. Перекрывающиеся окна
    с разными наборами строк сохраняются, а полностью эквивалентные окна
    объединяются.

    Поиск пар выполняется одним проходом для каждой ширины окна. При
    сдвиге окна старые пары удаляются лениво из max-heap, а для новой
    точки добавляются только пары с крайними по времени совместимыми
    точками. Этого достаточно для максимальной разницы дат и не требует
    повторного полного O(n²) поиска для каждого из тысяч окон.
    """

    interval_df = df.sort_values("date").reset_index(drop=True)

    dates = interval_df["date"].to_numpy(dtype="datetime64[ns]")
    date_ns = dates.astype("int64")
    temperatures = interval_df["t"].to_numpy(dtype=float)
    pressures = interval_df["p"].to_numpy(dtype=float)
    vna_values = interval_df["vna"].to_numpy(dtype=float)
    tkk_values = interval_df["tkk"].to_numpy(dtype=float)
    pkk_values = interval_df["pkk"].to_numpy(dtype=float)
    pi_k_values = interval_df["pi_k"].to_numpy(dtype=float)

    if len(interval_df) < 2:
        return []

    # Каждая точка попадает в десятую долю градуса. Правая граница
    # интервала открыта, как и в прежнем поиске по гистограмме.
    vna_cells = np.floor(
        np.clip(vna_values, 0, 100 - 1e-9) / VNA_INTERVAL_STEP
    ).astype(int)
    vna_cells = np.clip(vna_cells, 0, 1000 - 1)
    groups = [np.flatnonzero(vna_cells == cell) for cell in range(1000)]

    min_cell = int(vna_cells.min())
    max_cell = int(vna_cells.max())
    # Несколько разных границ могут выбрать один и тот же набор строк,
    # если между ними нет измерений. Храним только один представитель
    # каждого набора; при совпадении оставляем самое узкое окно.
    unique_candidates = {}

    for width_cells in range(
        int(round(VNA_MIN_INTERVAL_WIDTH / VNA_INTERVAL_STEP)),
        int(round(VNA_MAX_INTERVAL_WIDTH / VNA_INTERVAL_STEP)) + 1,
    ):
        start_min = min_cell
        start_max = min(max_cell, 1000 - width_cells)
        if start_min > start_max:
            continue

        active_flags = np.zeros(len(interval_df), dtype=bool)
        active_lists = [[] for _ in range(1000)]
        pair_heap = []
        active_count = 0

        def add_cell(cell):
            nonlocal active_count

            if cell < 0 or cell >= len(groups):
                return

            for new_index in groups[cell]:
                # Все точки текущего окна, включая уже добавленные точки
                # этой же ячейки, являются возможными партнёрами.
                parts = [
                    active_lists[current_cell]
                    for current_cell in range(
                        current_start,
                        current_start + width_cells,
                    )
                    if active_lists[current_cell]
                ]

                if parts:
                    other_indices = np.asarray(
                        [index for part in parts for index in part],
                        dtype=int,
                    )
                    valid = (
                        np.abs(temperatures[other_indices] - temperatures[new_index])
                        <= MAX_DELTA_T
                    ) & (
                        np.abs(pressures[other_indices] - pressures[new_index])
                        <= MAX_DELTA_P
                    )
                    valid_indices = other_indices[valid]

                    if valid_indices.size:
                        # Для максимальной разницы дат достаточно самой
                        # ранней и самой поздней совместимой точки.
                        extremes = {
                            int(valid_indices[np.argmin(date_ns[valid_indices])]),
                            int(valid_indices[np.argmax(date_ns[valid_indices])]),
                        }
                        for other_index in extremes:
                            left, right = sorted((int(other_index), int(new_index)))
                            delta_ns = int(date_ns[right] - date_ns[left])
                            heapq.heappush(
                                pair_heap,
                                (-delta_ns, left, right),
                            )

                active_flags[new_index] = True
                active_lists[cell].append(int(new_index))
                active_count += 1

        for current_start in range(start_min, start_max + 1):
            if current_start == start_min:
                for cell in range(current_start, current_start + width_cells):
                    add_cell(cell)
            else:
                # В предыдущей позиции окна уже были подготовлены все
                # точки, кроме входящей справа ячейки. Здесь меняем окно
                # на одну десятую и добавляем эту ячейку в его контексте.
                leaving_cell = current_start - 1
                leaving_indices = groups[leaving_cell]
                if leaving_indices.size:
                    active_flags[leaving_indices] = False
                    active_count -= int(leaving_indices.size)
                active_lists[leaving_cell].clear()
                add_cell(current_start + width_cells - 1)

            # Сначала убираем из heap пары, у которых хотя бы одна точка
            # уже вышла за левую границу окна.
            while pair_heap and (
                not active_flags[pair_heap[0][1]]
                or not active_flags[pair_heap[0][2]]
            ):
                heapq.heappop(pair_heap)

            if pair_heap:
                _, best_i, best_j = pair_heap[0]
                start_value = current_start * VNA_INTERVAL_STEP
                end_value = (current_start + width_cells) * VNA_INTERVAL_STEP
                pair = _build_pair_result(
                    interval_df,
                    dates,
                    temperatures,
                    pressures,
                    vna_values,
                    tkk_values,
                    pkk_values,
                    pi_k_values,
                    best_i,
                    best_j,
                )
                pair.update({
                    "vna_from": start_value,
                    "vna_to": end_value,
                    "vna_interval": f"{start_value:.1f}-{end_value:.1f}",
                    "count": int(active_count),
                    "share_percent": active_count / len(interval_df) * 100,
                })
                row_signature = tuple(np.flatnonzero(active_flags).tolist())
                candidate_key = (width_cells, current_start)
                previous = unique_candidates.get(row_signature)
                if previous is None or candidate_key < previous[0]:
                    unique_candidates[row_signature] = (candidate_key, pair)

    return [pair for _, pair in unique_candidates.values()]


def analyze_period(df, period_number, show_plot=True):
    """Считает распределение и гибкие интервалы ВНА внутри периода."""

    print()
    print("ДЕГРАДАЦИЯ")
    print("#" * 80)
    print(
        f"### ПЕРИОД {period_number}: "
        f"{df['date'].min():%d-%m-%Y %H:%M} .. "
        f"{df['date'].max():%d-%m-%Y %H:%M} "
        f"({len(df)} записей)"
    )
    print("#" * 80)

    df = df[
        (df["vna"] >= 0)
        & (df["vna"] <= 100)
    ].copy()
    if df.empty:
        raise ValueError("Нет корректных данных.")

    print()
    print("=" * 80)
    print("ИСХОДНЫЕ ДАННЫЕ")
    print("=" * 80)
    print(f"Количество строк: {len(df)}")
    print(f"Минимум VNA: {df['vna'].min():.3f}")
    print(f"Максимум VNA: {df['vna'].max():.3f}")

    # Обзорная гистограмма остаётся с шагом 1°.
    bins = np.arange(0, 101, 1)
    counts, edges = np.histogram(df["vna"], bins=bins)
    distribution = pd.DataFrame({
        "vna_from": edges[:-1],
        "vna_to": edges[1:],
        "count": counts,
    })
    distribution["interval"] = (
        distribution["vna_from"].astype(int).astype(str)
        + "-"
        + distribution["vna_to"].astype(int).astype(str)
    )
    distribution["share_percent"] = (
        distribution["count"] / distribution["count"].sum() * 100
    )

    figure = plt.figure(figsize=(14, 7))
    plt.bar(
        distribution["vna_from"],
        distribution["count"],
        width=1,
        align="edge",
        edgecolor="black",
    )
    plt.xlabel("VNA, %")
    plt.ylabel("Количество измерений")
    plt.title("Распределение времени работы ГТУ по положению VNA")
    plt.xticks(np.arange(0, 101, 5))
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    if show_plot:
        plt.show()

    candidates = _find_flexible_vna_intervals(df)
    result_df = pd.DataFrame(candidates)

    if not result_df.empty:
        candidates_before_eta_filter = len(result_df)
        result_df = result_df[
            result_df["delta_eta"] < MAX_DELTA_ETA
        ].copy()
        print(
            f"Фильтр TOP-10: Δη < {MAX_DELTA_ETA:.1f} п.п.; "
            f"осталось {len(result_df)} из {candidates_before_eta_filter} кандидатов"
        )

    if result_df.empty:
        print()
        print("TOP-10 ИНТЕРВАЛОВ VNA ПО МАКСИМАЛЬНОМУ РАССТОЯНИЮ")
        print("Подходящих пар точек не найдено.")
        return result_df, figure

    result_df = result_df.drop(columns=["vna_from", "vna_to"])
    result_df = result_df.sort_values(
        by=["delta_days", "count", "delta_eta"],
        ascending=[False, False, True],
    ).head(TOP_INTERVALS).reset_index(drop=True)
    result_df.insert(0, "rank", np.arange(1, len(result_df) + 1))

    # Сохраняем прежний состав и порядок полей итоговой таблицы. Внутренние
    # энтальпии нужны только для расчёта КПД и в отчёт не выводятся.
    result_df = result_df[
        [
            "rank",
            "vna_interval",
            "count",
            "share_percent",
            "date_1",
            "t_1",
            "p_1",
            "vna_1",
            "tkk_1",
            "pi_k_1",
            "eta_1",
            "date_2",
            "t_2",
            "p_2",
            "vna_2",
            "tkk_2",
            "pi_k_2",
            "eta_2",
            "delta_t",
            "delta_p",
            "delta_days",
            "delta_eta",
        ]
    ]

    print()
    print("=" * 100)
    print("TOP-10 ИНТЕРВАЛОВ VNA ПО МАКСИМАЛЬНОМУ РАССТОЯНИЮ")
    print("=" * 100)
    print(
        result_df[
            ["rank", "vna_interval", "count", "share_percent", "delta_days"]
        ].to_string(index=False)
    )

    # Округляем только числовые столбцы. Даты и timedelta округлять через
    # DataFrame.round нельзя: pandas выдаёт предупреждение.
    numeric_columns = result_df.select_dtypes(include="number").columns
    result_df[numeric_columns] = result_df[numeric_columns].round(3)

    display_df = result_df.drop(columns=["share_percent"]).copy()
    for column in ["date_1", "date_2"]:
        display_df[column] = pd.to_datetime(display_df[column]).dt.strftime(
            "%d-%m-%Y %H:%M"
        )

    # Разделители группируют метаданные, точку 1, точку 2 и дельты.
    display_df.insert(3, "│₁", "│")
    display_df.insert(display_df.columns.get_loc("eta_1") + 1, "║", "║")
    display_df.insert(display_df.columns.get_loc("eta_2") + 1, "│₂", "│")

    print()
    print("=" * 160)
    print("ИТОГОВАЯ ТАБЛИЦА ПО TOP-10 ИНТЕРВАЛАМ VNA")
    print("=" * 160)
    print(display_df.to_string(index=False))

    return result_df, figure


# ============================================================
# ПРОГОН ПО КАЖДОМУ ПЕРИОДУ
# ============================================================

def main(file_path=None, sheet_name="Данные", data=None):
    if data is None:
        if file_path is None:
            raise ValueError("Не задан файл данных для ВНА.")
        data = load_data(file_path, sheet_name)
    return run_vna(data)


if __name__ == "__main__":
    apply_cli_overrides()
    main(FILE_NAME, SHEET_NAME)
