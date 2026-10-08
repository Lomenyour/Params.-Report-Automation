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


MAX_DELTA_T = 1.0      # °C
MAX_DELTA_P = 0.1      # мбар

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

    for row in periods_df.itertuples(index=False):
        print(
            f"  Период {int(row.period)}: "
            f"{row.date_start:%d-%m-%Y %H:%M} "
            f"→ {row.date_end:%d-%m-%Y %H:%M} "
            f"| {row.duration_days:.2f} сут "
            f"| {row.records} записей"
        )

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
            results.append(result_df)

    return df, periods_df, results, figures



def analyze_period(df, period_number, show_plot=True):
    """Полный расчёт ВНА внутри одного периода работы ГТУ."""

    print()
    print("#" * 80)
    print(
        f"### ПЕРИОД {period_number}: "
        f"{df['date'].min():%d-%m-%Y %H:%M} .. "
        f"{df['date'].max():%d-%m-%Y %H:%M} "
        f"({len(df)} записей)"
    )
    print("#" * 80)

    # ============================================================
    # ФИЛЬТР VNA
    # ============================================================

    df = df[
        (df["vna"] >= 0)
        &
        (df["vna"] <= 100)
    ].copy()


    if df.empty:
        raise ValueError(
            "Нет корректных данных."
        )


    print()
    print("=" * 80)
    print("ИСХОДНЫЕ ДАННЫЕ")
    print("=" * 80)

    print(
        f"Количество строк: {len(df)}"
    )

    print(
        f"Минимум VNA: {df['vna'].min():.3f}"
    )

    print(
        f"Максимум VNA: {df['vna'].max():.3f}"
    )


    # ============================================================
    # РАСПРЕДЕЛЕНИЕ VNA
    # ============================================================

    bins = np.arange(
        0,
        101,
        1
    )


    counts, edges = np.histogram(
        df["vna"],
        bins=bins
    )


    distribution = pd.DataFrame({

        "vna_from": edges[:-1],

        "vna_to": edges[1:],

        "count": counts
    })


    distribution["interval"] = (
        distribution["vna_from"]
        .astype(int)
        .astype(str)
        +
        "-"
        +
        distribution["vna_to"]
        .astype(int)
        .astype(str)
    )


    distribution["share_percent"] = (
        distribution["count"]
        /
        distribution["count"].sum()
        *
        100
    )


    # ============================================================
    # TOP-10 ИНТЕРВАЛОВ
    # ============================================================

    top_intervals = (
        distribution
        .sort_values(
            "count",
            ascending=False
        )
        .head(TOP_INTERVALS)
        .reset_index(drop=True)
    )


    print()
    print("=" * 80)
    print("TOP-10 ИНТЕРВАЛОВ VNA")
    print("=" * 80)

    print(
        top_intervals[
            [
                "interval",
                "count",
                "share_percent"
            ]
        ].to_string(
            index=False
        )
    )


    # ============================================================
    # ГИСТОГРАММА
    # ============================================================

    figure = plt.figure(
        figsize=(14, 7)
    )

    plt.bar(
        distribution["vna_from"],
        distribution["count"],
        width=1,
        align="edge",
        edgecolor="black"
    )

    plt.xlabel(
        "VNA, %"
    )

    plt.ylabel(
        "Количество измерений"
    )

    plt.title(
        "Распределение времени работы ГТУ "
        "по положению VNA"
    )

    plt.xticks(
        np.arange(
            0,
            101,
            5
        )
    )

    plt.grid(
        axis="y",
        alpha=0.3
    )

    plt.tight_layout()

    if show_plot:
        plt.show()


    # ============================================================
    # ФУНКЦИЯ ПОИСКА ЛУЧШЕЙ ПАРЫ
    # ============================================================

    def find_best_pair(interval_df):

        interval_df = (
            interval_df
            .sort_values("date")
            .reset_index(drop=True)
        )


        if len(interval_df) < 2:
            return None


        dates = (
            interval_df["date"]
            .to_numpy()
        )

        temperatures = (
            interval_df["t"]
            .to_numpy(dtype=float)
        )

        pressures = (
            interval_df["p"]
            .to_numpy(dtype=float)
        )

        vna_values = (
            interval_df["vna"]
            .to_numpy(dtype=float)
        )

        tkk_values = (
            interval_df["tkk"]
            .to_numpy(dtype=float)
        )

        pkk_values = (
            interval_df["pkk"]
            .to_numpy(dtype=float)
        )


        n = len(interval_df)


        best_i = None
        best_j = None
        best_delta_ns = -1


        # ========================================================
        # ПОИСК САМОЙ ДАЛЕКОЙ ПО ВРЕМЕНИ ПАРЫ
        # ========================================================

        for i in range(n - 1):

            valid = (

                (
                    np.abs(
                        temperatures[i + 1:]
                        -
                        temperatures[i]
                    )
                    <= MAX_DELTA_T
                )

                &

                (
                    np.abs(
                        pressures[i + 1:]
                        -
                        pressures[i]
                    )
                    <= MAX_DELTA_P
                )

            )


            valid_indices = np.flatnonzero(
                valid
            )


            if valid_indices.size == 0:
                continue


            # Самая поздняя допустимая точка
            local_j = valid_indices[-1]

            j = i + 1 + local_j


            delta_time = (
                dates[j]
                -
                dates[i]
            )


            delta_ns = (
                delta_time
                .astype("timedelta64[ns]")
                .astype(np.int64)
            )


            if delta_ns > best_delta_ns:

                best_delta_ns = int(delta_ns)

                best_i = i
                best_j = j


        if best_i is None:
            return None


        i = best_i
        j = best_j


        # ========================================================
        # ДАННЫЕ ТОЧКИ 1
        # ========================================================

        date1 = pd.Timestamp(
            dates[i]
        )

        t1 = temperatures[i]
        p1 = pressures[i]
        vna1 = vna_values[i]

        tkk1 = tkk_values[i]
        pkk1 = pkk_values[i]


        # ========================================================
        # ДАННЫЕ ТОЧКИ 2
        # ========================================================

        date2 = pd.Timestamp(
            dates[j]
        )

        t2 = temperatures[j]
        p2 = pressures[j]
        vna2 = vna_values[j]

        tkk2 = tkk_values[j]
        pkk2 = pkk_values[j]


        # ========================================================
        # РАЗНИЦЫ
        # ========================================================

        delta_t = abs(
            t2 - t1
        )

        delta_p = abs(
            p2 - p1
        )


        delta_time = (
            date2 - date1
        )


        delta_days = (
            delta_time.total_seconds()
            /
            86400
        )


        # ========================================================
        # РАСЧЕТ КПД ТОЧКИ 1
        # ========================================================

        eta1, h1_1, h2_1, h2s_1 = (
            calculate_compressor_efficiency(
                t1,
                p1,
                tkk1,
                pkk1
            )
        )


        # ========================================================
        # РАСЧЕТ КПД ТОЧКИ 2
        # ========================================================

        eta2, h1_2, h2_2, h2s_2 = (
            calculate_compressor_efficiency(
                t2,
                p2,
                tkk2,
                pkk2
            )
        )


        # ========================================================
        # ДЕЛЬТА КПД
        # ========================================================

        delta_eta = abs(
            eta2 - eta1
        )


        return {

            "date_1": date1,

            "t_1": t1,
            "p_1": p1,
            "vna_1": vna1,

            "tkk_1": tkk1,
            "pkk_1": pkk1,

            "eta_1": eta1,

            "h1_1": h1_1,
            "h2_1": h2_1,
            "h2s_1": h2s_1,


            "date_2": date2,

            "t_2": t2,
            "p_2": p2,
            "vna_2": vna2,

            "tkk_2": tkk2,
            "pkk_2": pkk2,

            "eta_2": eta2,

            "h1_2": h1_2,
            "h2_2": h2_2,
            "h2s_2": h2s_2,


            "delta_t": delta_t,

            "delta_p": delta_p,

            "delta_days": delta_days,

            "delta_eta": delta_eta
        }


    # ============================================================
    # ПОИСК ДЛЯ КАЖДОГО ИЗ TOP-10 ИНТЕРВАЛОВ
    # ============================================================

    results = []


    for rank, row in top_intervals.iterrows():

        vna_min = row["vna_from"]
        vna_max = row["vna_to"]

        interval_name = row["interval"]

        count = int(row["count"])
        share = float(row["share_percent"])

        interval_df = df[
            (df["vna"] >= vna_min)
            &
            (df["vna"] < vna_max)
        ].copy()

        best_pair = find_best_pair(interval_df)

        if best_pair is None:

            results.append({
                "rank": rank + 1,
                "vna_interval": interval_name,
                "count": count,
                "share_percent": share,

                "date_1": None,
                "t_1": None,
                "p_1": None,
                "vna_1": None,
                "tkk_1": None,
                "pkk_1": None,
                "eta_1": None,

                "date_2": None,
                "t_2": None,
                "p_2": None,
                "vna_2": None,
                "tkk_2": None,
                "pkk_2": None,
                "eta_2": None,

                "delta_t": None,
                "delta_p": None,
                "delta_days": None,
                "delta_eta": None
            })

            continue


        # ========================================================
        # ДОБАВЛЯЕМ В ИТОГОВУЮ ТАБЛИЦУ
        # ========================================================

        results.append({
            "rank": rank + 1,
            "vna_interval": interval_name,
            "count": count,
            "share_percent": share,

            "date_1": best_pair["date_1"],
            "t_1": best_pair["t_1"],
            "p_1": best_pair["p_1"],
            "vna_1": best_pair["vna_1"],
            "tkk_1": best_pair["tkk_1"],
            "pkk_1": best_pair["pkk_1"],
            "eta_1": best_pair["eta_1"],

            "date_2": best_pair["date_2"],
            "t_2": best_pair["t_2"],
            "p_2": best_pair["p_2"],
            "vna_2": best_pair["vna_2"],
            "tkk_2": best_pair["tkk_2"],
            "pkk_2": best_pair["pkk_2"],
            "eta_2": best_pair["eta_2"],

            "delta_t": best_pair["delta_t"],
            "delta_p": best_pair["delta_p"],
            "delta_days": best_pair["delta_days"],
            "delta_eta": best_pair["delta_eta"]
        })


    # ============================================================
    # ИТОГОВАЯ ТАБЛИЦА В ТЕРМИНАЛЕ
    # ============================================================

    result_df = pd.DataFrame(results)

    # Округляем только числовые столбцы. Даты и timedelta округлять через
    # DataFrame.round нельзя: pandas выдаёт предупреждение.
    numeric_columns = result_df.select_dtypes(include="number").columns
    result_df[numeric_columns] = result_df[numeric_columns].round(3)

    # Сортировка по двум столбцам:
    # 1) по максимальной разнице в днях (сначала самые длинные)
    # 2) при равенстве - по МИНИМАЛЬНОЙ delta_eta: нужна самая мелкая
    #    разница КПД между точками
    result_df = result_df.sort_values(
        by=["delta_days", "delta_eta"],
        ascending=[False, True]
    ).reset_index(drop=True)


    # ============================================================
    # ТАБЛИЦА ДЛЯ ВЫВОДА
    #
    # Даты — в читаемом виде (дд-мм-гггг чч:мм).
    # Колонка доли времени share_percent убрана, чтобы таблица
    # влезала в терминал. Полные данные остаются в result_df.
    # ============================================================

    display_df = (
        result_df
        .drop(columns=["share_percent"])
        .copy()
    )

    for column in ["date_1", "date_2"]:

        if column in display_df.columns:

            display_df[column] = (
                pd.to_datetime(display_df[column])
                .dt.strftime("%d-%m-%Y %H:%M")
            )


    print()
    print("=" * 160)
    print("ИТОГОВАЯ ТАБЛИЦА ПО TOP-10 ИНТЕРВАЛАМ VNA")
    print("=" * 160)

    print(
        display_df.to_string(
            index=False
        )
    )

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
