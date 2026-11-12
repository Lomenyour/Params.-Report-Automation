import pandas as pd
import numpy as np
import heapq
from pathlib import Path


# ============================================================
# НАСТРОЙКИ
# ============================================================

FILE_NAME = Path(__file__).resolve().parents[1] / "data" / "degradation.xlsx"

# Допустимые различия между двумя точками
MAX_DELTA_T = 1.0      # °C
MAX_DELTA_P = 0.1      # мбар

# Диапазон ВНА задаём вручную
VNA_MIN =85.0
VNA_MAX = 86.0

# Сколько лучших пар нужно найти
NUMBER_OF_PAIRS = 3


# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

df = pd.read_excel(
    FILE_NAME,
    usecols=["date", "t", "p", "vna"]
)

# Убираем пробелы и приводим имена столбцов к нижнему регистру
df.columns = df.columns.str.strip().str.lower()


# ============================================================
# ПРЕОБРАЗОВАНИЕ ТИПОВ
# ============================================================

df["date"] = pd.to_datetime(
    df["date"],
    errors="coerce"
)

df["t"] = pd.to_numeric(
    df["t"],
    errors="coerce"
)

df["p"] = pd.to_numeric(
    df["p"],
    errors="coerce"
)

df["vna"] = pd.to_numeric(
    df["vna"],
    errors="coerce"
)

# Удаляем строки с некорректными значениями
df = df.dropna(
    subset=["date", "t", "p", "vna"]
)


# ============================================================
# ФИЛЬТР ПО ВНА
# ============================================================

df = df[
    (df["vna"] >= VNA_MIN) &
    (df["vna"] <= VNA_MAX)
].copy()

if df.empty:
    raise ValueError(
        f"Нет записей в диапазоне ВНА "
        f"{VNA_MIN} - {VNA_MAX}"
    )

print(
    f"Количество записей после фильтра по ВНА "
    f"{VNA_MIN}-{VNA_MAX}: {len(df)}"
)


# ============================================================
# СОРТИРОВКА ПО ДАТЕ
# ============================================================

df = df.sort_values("date").reset_index(drop=True)


# ============================================================
# ПЕРЕВОД В NUMPY
# ============================================================

dates = df["date"].to_numpy()
temperatures = df["t"].to_numpy(dtype=float)
pressures = df["p"].to_numpy(dtype=float)
vna_values = df["vna"].to_numpy(dtype=float)

n = len(df)


# ============================================================
# ПОИСК 3 ЛУЧШИХ ПАР
# ============================================================

best_pairs = []

for i in range(n - 1):

    # Проверяем все последующие точки сразу
    valid = (
        (np.abs(temperatures[i + 1:] - temperatures[i])
         <= MAX_DELTA_T)
        &
        (np.abs(pressures[i + 1:] - pressures[i])
         <= MAX_DELTA_P)
    )

    valid_indices = np.flatnonzero(valid)

    if valid_indices.size == 0:
        continue

    # Для точного TOP-3 достаточно рассмотреть
    # последние 3 подходящие точки для каждого i,
    # потому что данные отсортированы по времени
    for local_j in valid_indices[-NUMBER_OF_PAIRS:]:

        j = i + 1 + local_j

        delta_time = dates[j] - dates[i]

        delta_ns = (
            delta_time
            .astype("timedelta64[ns]")
            .astype(np.int64)
        )

        pair = (
            int(delta_ns),
            i,
            j
        )

        if len(best_pairs) < NUMBER_OF_PAIRS:

            heapq.heappush(
                best_pairs,
                pair
            )

        elif delta_ns > best_pairs[0][0]:

            heapq.heapreplace(
                best_pairs,
                pair
            )


# ============================================================
# СОРТИРОВКА РЕЗУЛЬТАТОВ
# ============================================================

best_pairs.sort(
    key=lambda x: x[0],
    reverse=True
)


# ============================================================
# ВЫВОД
# ============================================================

if len(best_pairs) == 0:

    print("Подходящих пар не найдено.")

else:

    print()
    print("=" * 80)
    print(
        f"TOP-{NUMBER_OF_PAIRS} ПАР "
        f"ДЛЯ ВНА {VNA_MIN}-{VNA_MAX}"
    )
    print("=" * 80)

    results = []

    for number, (_, i, j) in enumerate(
        best_pairs,
        start=1
    ):

        date1 = pd.Timestamp(dates[i])
        date2 = pd.Timestamp(dates[j])

        t1 = temperatures[i]
        t2 = temperatures[j]

        p1 = pressures[i]
        p2 = pressures[j]

        vna1 = vna_values[i]
        vna2 = vna_values[j]

        delta_t = abs(t2 - t1)
        delta_p = abs(p2 - p1)

        delta_time = date2 - date1
        delta_days = (
            delta_time.total_seconds() / 86400
        )

        print()
        print(f"ПАРА №{number}")
        print("-" * 80)

        print("Точка 1:")
        print(f"  Дата:        {date1}")
        print(f"  Температура: {t1:.3f}")
        print(f"  Давление:    {p1:.4f}")
        print(f"  ВНА:         {vna1:.3f}")

        print()

        print("Точка 2:")
        print(f"  Дата:        {date2}")
        print(f"  Температура: {t2:.3f}")
        print(f"  Давление:    {p2:.4f}")
        print(f"  ВНА:         {vna2:.3f}")

        print()

        print(f"ΔT:       {delta_t:.3f} °C")
        print(f"ΔP:       {delta_p:.4f} мбар")
        print(f"Δвремя:   {delta_days:.2f} дней")

        results.append({
            "pair": number,

            "date_1": date1,
            "t_1": t1,
            "p_1": p1,
            "vna_1": vna1,

            "date_2": date2,
            "t_2": t2,
            "p_2": p2,
            "vna_2": vna2,

            "delta_t": delta_t,
            "delta_p": delta_p,
            "delta_days": delta_days
        })


# ============================================================
# СОХРАНЕНИЕ В EXCEL
# ============================================================

    result_df = pd.DataFrame(results)

    

    # print()
    # print(
    #     "Результат сохранён в "
    #     "degradation_result.xlsx"
    # )
