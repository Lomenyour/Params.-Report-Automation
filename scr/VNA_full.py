import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

from CoolProp.CoolProp import PropsSI


# ============================================================
# НАСТРОЙКИ
# ============================================================

FILE_NAME = Path(__file__).resolve().parents[1] / "data" / "degradation.xlsx"

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


# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

df = pd.read_excel(
    FILE_NAME,
    usecols=["date", "t", "p", "vna", "tkk", "pkk"]
)

df.columns = df.columns.str.strip().str.lower()


# ============================================================
# ПРЕОБРАЗОВАНИЕ ТИПОВ
# ============================================================

df["date"] = pd.to_datetime(
    df["date"],
    errors="coerce"
)

for column in ["t", "p", "vna", "tkk", "pkk"]:

    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


df = df.dropna(
    subset=[
        "date",
        "t",
        "p",
        "vna",
        "tkk",
        "pkk"
    ]
).copy()


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

plt.figure(
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

    print()
    print("=" * 90)

    print(
        f"ИНТЕРВАЛ №{rank + 1}: "
        f"VNA {interval_name}"
    )

    print(
        f"Количество записей: {count}"
    )

    print("=" * 90)


    if best_pair is None:

        print(
            "Подходящая пара не найдена."
        )

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
    # ТОЧКА 1
    # ========================================================

    print()
    print("ТОЧКА 1")
    print("-" * 50)

    print(
        f"Дата:                 "
        f"{best_pair['date_1']}"
    )

    print(
        f"Температура входа:    "
        f"{best_pair['t_1']:.3f} °C"
    )

    print(
        f"Давление входа:       "
        f"{best_pair['p_1']:.4f} мбар"
    )

    print(
        f"VNA:                  "
        f"{best_pair['vna_1']:.3f}"
    )

    print(
        f"Температура выхода:   "
        f"{best_pair['tkk_1']:.3f} °C"
    )

    print(
        f"Давление выхода:      "
        f"{best_pair['pkk_1']:.4f} бар"
    )

    print(
        f"КПД компрессора:      "
        f"{best_pair['eta_1']:.3f} %"
    )


    # ========================================================
    # ТОЧКА 2
    # ========================================================

    print()
    print("ТОЧКА 2")
    print("-" * 50)

    print(
        f"Дата:                 "
        f"{best_pair['date_2']}"
    )

    print(
        f"Температура входа:    "
        f"{best_pair['t_2']:.3f} °C"
    )

    print(
        f"Давление входа:       "
        f"{best_pair['p_2']:.4f} мбар"
    )

    print(
        f"VNA:                  "
        f"{best_pair['vna_2']:.3f}"
    )

    print(
        f"Температура выхода:   "
        f"{best_pair['tkk_2']:.3f} °C"
    )

    print(
        f"Давление выхода:      "
        f"{best_pair['pkk_2']:.4f} бар"
    )

    print(
        f"КПД компрессора:      "
        f"{best_pair['eta_2']:.3f} %"
    )


    # ========================================================
    # СРАВНЕНИЕ
    # ========================================================

    print()
    print("СРАВНЕНИЕ")
    print("-" * 50)

    print(
        f"ΔT входа:             "
        f"{best_pair['delta_t']:.3f} °C"
    )

    print(
        f"ΔP входа:             "
        f"{best_pair['delta_p']:.4f} мбар"
    )

    print(
        f"Δвремя:               "
        f"{best_pair['delta_days']:.2f} дней"
    )

    print(
        f"КПД точки 1:          "
        f"{best_pair['eta_1']:.3f} %"
    )

    print(
        f"КПД точки 2:          "
        f"{best_pair['eta_2']:.3f} %"
    )

    print(
        f"ΔКПД:                 "
        f"{best_pair['delta_eta']:.3f} п.п."
    )


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

# Округляем все числовые столбцы до 3 знаков
result_df = result_df.round(3)

result_df = pd.DataFrame(results)

# Округляем числовые столбцы
result_df = result_df.round(3)

# Сортировка:
# 1) по максимальной разнице в днях
# 2) при равенстве - по максимальной delta_eta
result_df = result_df.sort_values(
    by=["delta_days", "delta_eta"],
    ascending=[False, False]
).reset_index(drop=True)

print()
print("=" * 160)
print("ИТОГОВАЯ ТАБЛИЦА ПО TOP-10 ИНТЕРВАЛАМ VNA")
print("=" * 160)

print(
    result_df.to_string(
        index=False
    )
)
