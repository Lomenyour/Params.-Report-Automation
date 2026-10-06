import re
import sys

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

from CoolProp.CoolProp import PropsSI


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

FILE_NAME = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "СызТЭЦ ГТ-11 2кв 2026.xlsm"
)

# Правило 0.2: читаем только первый лист — "Данные"
SHEET_NAME = "Данные"

MAX_DELTA_T = 1.0      # °C
MAX_DELTA_P = 0.1      # мбар

TOP_INTERVALS = 10


# ============================================================
# МАППИНГ КОЛОНОК
#
# Взят из scr/merge_data.py (COLUMN_MAP). Оставлены только те
# колонки, которые нужны расчёту:
#   - VNA_full: дата, Тнк, Pнк, ВНА, Ткк, Ркк;
#   - RH_raschet (будет вызываться отсюда): Nприв, Вприв.
# Ключи — как встречаются в шапке Excel (регистр не важен),
# значения — канонические имена.
# ============================================================

COLUMN_MAP = {
    # --- дата ---
    "дата": "Дата", "date": "Дата", "time": "Дата", "дата/время": "Дата",

    # --- VNA_full ---
    "pатм.": "Pатм.", "pатм": "Pатм.", "ратм": "Pатм.", "pатм, па": "Pатм.",
    "тнк": "Тнк", "tнк": "Тнк", "тнк, °с": "Тнк",
    "pнк": "Pнк", "рнк": "Pнк", "pнк, мбар": "Pнк",
    "вна": "ВНА",
    "ткк": "Ткк", "tкк": "Ткк", "ткк, °с": "Ткк",
    "pкк": "Ркк", "ркк": "Ркк", "ркк, бар": "Ркк",

    # --- RH_raschet: приведённая мощность ---
    "nприв": "Nприв", "nприв, мвт": "Nприв", "n прив": "Nприв",
    "nприв,мвт": "Nприв", "nприв (мвт)": "Nприв",
    "приведенная мощность": "Nприв", "приведённая мощность": "Nприв",

    # --- RH_raschet: приведённый расход газа (объёмный, нм3/ч) ---
    "вприв": "Вприв", "bприв, нм3/ч": "Вприв", "bприв, нм³/ч": "Вприв",
    "вприв, нм3/ч": "Вприв", "вприв, нм³/ч": "Вприв", "bприв,нм3/ч": "Вприв",
    "приведенный расход газа": "Вприв", "приведённый расход газа": "Вприв",
    "приведенный расход": "Вприв", "приведённый расход": "Вприв",
    "расход газа": "Расход газа",

    # --- приведённый УДЕЛЬНЫЙ расход (нм3/(ч·МВт)) ---
    # Это НЕ то же самое, что Вприв: bприв = Bприв / Nприв.
    "bприв": "bприв", "b прив": "bприв",
}
COLUMN_MAP = {k.strip().lower(): v for k, v in COLUMN_MAP.items()}


# Короткие имена, под которыми колонки живут внутри расчёта.
# У одной короткой колонки может быть несколько канонических вариантов —
# берём первый найденный.
SHORT_NAMES = {
    "date": ["Дата"],
    "t": ["Тнк"],
    "vna": ["ВНА"],
    "tkk": ["Ткк"],

    # источники для приведения к единицам расчёта (см. ниже)
    "p_atm_pa": ["Pатм."],
    "p_nk_pa": ["Pнк"],
    "p_kk_mpa": ["Ркк"],

    # для будущего вызова RH_raschet
    "power": ["Nприв"],
    "fuel": ["Вприв", "Расход газа"],
    # приведённый УДЕЛЬНЫЙ расход — отдельная величина, не путать с fuel
    "fuel_specific": ["bприв"],
}


# Без этих колонок расчёт ВНА невозможен
REQUIRED_SHORT_NAMES = [
    "date",
    "t",
    "vna",
    "tkk",
    "p_atm_pa",
    "p_nk_pa",
    "p_kk_mpa",
]


# ============================================================
# ЧТЕНИЕ ШАПКИ (логика из scr/merge_data.py)
# ============================================================

def make_unique_headers(headers: list) -> list:
    seen: dict[str, int] = {}
    unique_headers = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            unique_headers.append(h)
    return unique_headers


def normalize_and_map_headers(raw_headers: list, column_map: dict) -> tuple[list, list]:
    mapped_headers = []
    unmapped_raw = []
    for col in raw_headers:
        col_str = "" if (col is None or pd.isna(col)) else str(col).strip()

        clean_full = re.sub(r"\s+", " ", col_str.replace("\n", " ")).strip().lower()
        clean_short = re.split(r"[,]", clean_full)[0].strip()

        if clean_full in column_map:
            mapped_headers.append(column_map[clean_full])
        elif clean_short in column_map:
            mapped_headers.append(column_map[clean_short])
        else:
            mapped_headers.append(clean_full if clean_full else "unnamed")
            if clean_full:
                unmapped_raw.append(col_str.replace("\n", " "))

    return make_unique_headers(mapped_headers), unmapped_raw


def find_header_row_by_map(
    file_path: Path,
    sheet_name: str,
    column_map: dict,
    min_matches: int = 2,
    max_rows: int = 25,
) -> int | None:
    """Ищет строку шапки в первых max_rows строках листа.

    Строка считается шапкой, если в ней встретилось минимум min_matches
    названий из маппинга.
    """
    try:
        df_head = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            header=None,
            nrows=max_rows,
            engine="calamine",
        )
        map_keys = set(column_map.keys())
        for idx, row in df_head.iterrows():
            vals = set()
            for v in row:
                if pd.notna(v):
                    v_str = str(v).strip().lower()
                    clean_full = re.sub(r"\s+", " ", v_str.replace("\n", " ")).strip()
                    clean_short = re.split(r"[,]", clean_full)[0].strip()
                    vals.add(clean_full)
                    vals.add(clean_short)
            if len(vals.intersection(map_keys)) >= min_matches:
                return idx
    except Exception as e:
        print(f"Ошибка поиска шапки на листе '{sheet_name}': {e}")
    return None


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
    # В данных есть строки останова — отрицательные/нулевые
    # давления. На них CoolProp падает с ValueError и роняет
    # весь расчёт. Такие точки помечаем как NaN.
    # --------------------------------------------------------

    if P1 <= 0 or P2 <= 0:

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


# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

xl = pd.ExcelFile(
    FILE_NAME,
    engine="calamine"
)

first_sheet = xl.sheet_names[0]

if str(first_sheet).strip() != SHEET_NAME:

    raise ValueError(
        f"Первый лист книги называется "
        f"'{first_sheet}', а ожидается "
        f"'{SHEET_NAME}'."
    )


header_row = find_header_row_by_map(
    FILE_NAME,
    SHEET_NAME,
    COLUMN_MAP
)

if header_row is None:

    raise ValueError(
        f"Не найдена строка шапки на листе "
        f"'{SHEET_NAME}' в файле {FILE_NAME.name}"
    )


head = pd.read_excel(
    FILE_NAME,
    sheet_name=SHEET_NAME,
    header=None,
    nrows=header_row + 1,
    engine="calamine"
)

raw_headers = (
    head
    .iloc[header_row]
    .tolist()
)


raw = pd.read_excel(
    FILE_NAME,
    sheet_name=SHEET_NAME,
    header=None,
    skiprows=header_row + 1,
    engine="calamine"
)

min_cols = min(
    raw.shape[1],
    len(raw_headers)
)

raw = raw.iloc[:, :min_cols]
raw_headers = raw_headers[:min_cols]


file_headers, unmapped_headers = (
    normalize_and_map_headers(
        raw_headers,
        COLUMN_MAP
    )
)

if unmapped_headers:

    print(
        f"Нераспознанные столбцы: "
        f"{', '.join(unmapped_headers)}"
    )


raw.columns = file_headers
raw = raw.dropna(how="all")


df = pd.DataFrame(index=raw.index)

for short_name, canonical_names in SHORT_NAMES.items():

    for canonical_name in canonical_names:

        if canonical_name in raw.columns:

            df[short_name] = raw[canonical_name]
            break


missing = [
    name
    for name in REQUIRED_SHORT_NAMES
    if name not in df.columns
]

if missing:

    raise ValueError(
        f"Не найдены обязательные колонки: "
        f"{missing}. "
        f"Распознанные заголовки: "
        f"{list(raw.columns)}"
    )


# ============================================================
# ПРИВЕДЕНИЕ К ЕДИНИЦАМ РАСЧЁТА
#
# В книге:
#   Pатм, Па   — атмосферное давление
#   Pнк,  Па   — потеря давления на входе
#   Ркк, МПа   — абсолютное давление на выходе
#
# calculate_compressor_efficiency ждёт:
#   p   — абсолютное давление на входе, мбар
#   pkk — абсолютное давление на выходе, бар
#
# Что вход именно (Pатм − Pнк), подтверждает колонка πк книги:
#   πк = Ркк / (Pатм − Pнк) — сходится точно.
# ============================================================

df["p"] = (
    pd.to_numeric(df["p_atm_pa"], errors="coerce")
    - pd.to_numeric(df["p_nk_pa"], errors="coerce")
) / 100.0

df["pkk"] = (
    pd.to_numeric(df["p_kk_mpa"], errors="coerce") * 10.0
)

df = df.drop(
    columns=["p_atm_pa", "p_nk_pa", "p_kk_mpa"]
)


df = df.copy()


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
