# -*- coding: utf-8 -*-
"""Расчёт экономических потерь по периодам работы ГТУ.

Модуль содержит только фактическую часть методики:

* перерасход топлива из наклона регрессии bприв по часам;
* недовыработку электроэнергии из наклона регрессии Nприв по часам;
* перевод натуральных величин в рубли по тарифам, введённым пользователем;
* сводную таблицу по периодам и строку ИТОГО.

Регрессия строится отдельно для каждого периода в его самом частом
однопроцентном интервале ВНА. Полученная потеря рассчитывается для каждой
рабочей строки всего периода, затем соседние получасовые значения усредняются
в часовое значение и эти средние складываются. Такой порядок соответствует
структуре расчёта в исходной книге: там промежуточные колонки содержат
среднее двух соседних получасовых потерь.

Порог ВНА берётся из распределения по принятым периодам с шагом 1° и покрытием 80 %
рабочих записей. Динамический порог мощности используется для отдельного
расчёта часов номинального режима, а экономические потери суммируются по
всему рабочему времени периода.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from periods import LOW_POWER


# Входные данные идут с шагом 30 минут.
DT_HOURS = 0.5
PAIR_WINDOW = 2
PAIR_STEP = 2

# Принятые фильтры качества измерений. Границы сохраняем строгими, как в
# исходной методике: выбросы на самих границах не проходят.
B_MIN, B_MAX = 150.0, 600.0
T_MIN, T_MAX = -40.0, 50.0

# Распределение ВНА для экономики: целые проценты, верхние интервалы до 80 %
# рабочего времени.
VNA_BIN_WIDTH = 1.0
WORKING_SHARE = 0.80
ANNUAL_HOURS = 8760.0


ECONOMICS_COLUMNS = [
    "Период",
    "Начало",
    "Конец",
    "Недовыработка, МВт·ч",
    "Недовыработка, руб",
    "Перерасход, нм³",
    "Перерасход, руб",
    "Общие издержки, руб",
    "Наработка, ч",
]


def _num(data: pd.DataFrame, name: str) -> np.ndarray:
    """Возвращает числовую колонку или массив NaN, если её нет."""

    if name not in data.columns:
        return np.full(len(data), np.nan, dtype=float)
    return pd.to_numeric(data[name], errors="coerce").to_numpy(dtype=float)


def _bpriv(data: pd.DataFrame) -> np.ndarray:
    """Берёт bприв или восстанавливает его как Вприв / Nприв."""

    b = _num(data, "fuel_specific")
    fuel = _num(data, "fuel")
    power = _num(data, "power")
    with np.errstate(divide="ignore", invalid="ignore"):
        derived = fuel / power
    return np.where(np.isfinite(b), b, derived)


def _ambient_temperature(data: pd.DataFrame) -> np.ndarray:
    """Возвращает температуру воздуха в каноническом имени загрузчика."""

    for name in ("ambient_temperature", "Токр.воздуха", "t"):
        if name in data.columns:
            return _num(data, name)
    return np.full(len(data), np.nan, dtype=float)


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, int]:
    """МНК для y = k*x + c."""

    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2 or np.unique(x[mask]).size < 2:
        return np.nan, np.nan, int(mask.sum())
    slope, intercept = np.polyfit(x[mask], y[mask], 1)
    return float(slope), float(intercept), int(mask.sum())


def _hourly_mean_sum(values: np.ndarray) -> float:
    """Суммирует средние двух соседних получасовых значений."""

    values = np.asarray(values, dtype=float)
    total = 0.0
    for start in range(0, len(values) - PAIR_WINDOW + 1, PAIR_STEP):
        mean = np.nanmean(values[start:start + PAIR_WINDOW])
        if np.isfinite(mean) and mean > 0.0:
            total += float(mean)
    return total


def _working_mask(data: pd.DataFrame) -> np.ndarray:
    power = _num(data, "power")
    return np.isfinite(power) & (power > LOW_POWER)


def build_vna_distribution(data: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    """Строит распределение ВНА по переданным принятым периодам и выбирает порог.

    Остановы исключаются по LOW_POWER. Начиная с верхних интервалов ВНА,
    выбирается набор, содержащий не менее 80 % рабочих записей. Нижняя
    граница последнего добавленного интервала становится порогом; рабочее
    условие далее задаётся как ВНА ≥ threshold.
    """

    vna = _num(data, "vna")
    valid = _working_mask(data) & np.isfinite(vna) & (vna >= 0.0) & (vna <= 100.0)
    values = vna[valid]
    bins = np.arange(0.0, 101.0, VNA_BIN_WIDTH)
    counts, edges = np.histogram(values, bins=bins)
    distribution = pd.DataFrame({
        "ВНА от, %": edges[:-1],
        "ВНА до, %": edges[1:],
        "Записей": counts,
    })
    total = int(counts.sum())
    distribution["Доля, %"] = (
        distribution["Записей"] / total * 100.0 if total else 0.0
    )

    if total == 0:
        distribution["Накопленная доля сверху, %"] = 0.0
        return distribution, None

    target = total * WORKING_SHARE
    accumulated = 0
    threshold = None
    cumulative = np.zeros(len(counts), dtype=float)
    for index in range(len(counts) - 1, -1, -1):
        accumulated += int(counts[index])
        cumulative[index] = accumulated / total * 100.0
        if threshold is None and accumulated >= target:
            threshold = float(edges[index])

    distribution["Накопленная доля сверху, %"] = cumulative
    return distribution, threshold


def _power_quality_mask(
    power: np.ndarray,
    b: np.ndarray,
    temperature: np.ndarray,
    power_threshold: float,
) -> np.ndarray:
    """Маска номинального режима и допустимых b/температуры."""

    temperature_ok = ~np.isfinite(temperature) | (
        (temperature > T_MIN) & (temperature < T_MAX)
    )
    return (
        np.isfinite(power)
        & (power > power_threshold)
        & np.isfinite(b)
        & (b > B_MIN)
        & (b < B_MAX)
        & temperature_ok
    )


def _period_mask(data: pd.DataFrame, period_number: int, period_row) -> np.ndarray:
    if "period" in data.columns:
        return (
            pd.to_numeric(data["period"], errors="coerce").to_numpy()
            == period_number
        )
    dates = pd.to_datetime(data["date"], errors="coerce")
    return (
        (dates >= period_row.date_start).to_numpy()
        & (dates <= period_row.date_end).to_numpy()
    )


def _merge_vna(data: pd.DataFrame, vna_data: pd.DataFrame | None) -> pd.DataFrame:
    """Добавляет ВНА, если его нет в RH-представлении данных."""

    result = data.copy()
    if "vna" in result.columns and pd.to_numeric(
        result["vna"], errors="coerce"
    ).notna().any():
        return result
    if vna_data is None or "vna" not in vna_data.columns:
        result["vna"] = np.nan
        return result

    right = vna_data[["date", "vna"]].copy()
    right["date"] = pd.to_datetime(right["date"], errors="coerce")
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    return result.drop(columns=["vna"], errors="ignore").merge(
        right.drop_duplicates("date"), on="date", how="left", sort=False
    )


def _period_vna_data(
    vna_data: pd.DataFrame | None,
    period_number: int,
    period_row,
) -> pd.DataFrame:
    """Возвращает ВНА-строки конкретного периода для выбора интервала."""

    if vna_data is None or "vna" not in vna_data.columns:
        return pd.DataFrame()
    if "period" in vna_data.columns:
        return vna_data[vna_data["period"] == period_number].copy()

    dates = pd.to_datetime(vna_data["date"], errors="coerce")
    return vna_data[
        (dates >= period_row.date_start) & (dates <= period_row.date_end)
    ].copy()


def _dominant_vna_interval(period_data: pd.DataFrame):
    """Возвращает самый частый интервал ВНА шириной 1 градус."""

    if period_data.empty:
        return None
    values = pd.to_numeric(period_data["vna"], errors="coerce")
    values = values[(values >= 0.0) & (values <= 100.0)].dropna()
    if values.empty:
        return None

    starts = np.floor(values).astype(int).clip(upper=99)
    counts = starts.value_counts()
    start = int(counts.index[0])
    return float(start), float(start + 1), int(counts.iloc[0])


def calculate_economics(
    data: pd.DataFrame,
    periods_df: pd.DataFrame,
    gas_price_rub_per_m3: float,
    electricity_price_rub_per_mwh: float,
    power_threshold: float,
    vna_data: pd.DataFrame | None = None,
    electricity_cost_rub_per_mwh: float = 0.0,
    delta_table: pd.DataFrame | None = None,
    nominal_hours: dict | None = None,
) -> dict:
    """Считает натуральные и денежные потери по каждому периоду.

    power_threshold передаётся из распределения мощности по принятым
    периодам в RH. Порог ВНА рассчитывается один раз по тем же периодам.
    Регрессия для каждого периода строится в его самом частом интервале ВНА
    шириной 1°.
    """

    combined = _merge_vna(data, vna_data)
    nominal_hours = nominal_hours or {}
    try:
        power_threshold = float(power_threshold)
    except (TypeError, ValueError):
        power_threshold = np.nan
    distribution, vna_threshold = build_vna_distribution(combined)
    power = _num(combined, "power")
    b = _bpriv(combined)
    vna = _num(combined, "vna")
    temperature = _ambient_temperature(combined)
    hours = _num(combined, "hours")
    dates = pd.to_datetime(combined["date"], errors="coerce")

    if vna_threshold is None:
        vna_threshold = np.nan

    try:
        electricity_cost_rub_per_mwh = float(electricity_cost_rub_per_mwh)
    except (TypeError, ValueError):
        electricity_cost_rub_per_mwh = 0.0
    electricity_margin = (
        float(electricity_price_rub_per_mwh) - electricity_cost_rub_per_mwh
    )

    periods = []
    row_losses = []
    period_durations = []
    for period_row in periods_df.itertuples(index=False):
        period_number = int(period_row.period)
        mask = _period_mask(combined, period_number, period_row)
        indices = np.flatnonzero(mask)
        if len(indices) == 0:
            continue

        order = indices[
            np.argsort(dates.iloc[indices].to_numpy(), kind="stable")
        ]
        period_hours = hours[order]
        period_durations.append(float(period_hours[-1] - period_hours[0]))
        if not np.isfinite(period_hours).any():
            tau = np.arange(len(order), dtype=float) * DT_HOURS
        else:
            first_hour = period_hours[0]
            tau = period_hours - first_hour
            tau = np.where(
                np.isfinite(tau),
                tau,
                np.arange(len(order), dtype=float) * DT_HOURS,
            )

        power_p = power[order]
        b_p = b[order]
        vna_p = vna[order]
        temperature_p = temperature[order]

        interval = _dominant_vna_interval(
            _period_vna_data(vna_data, period_number, period_row)
        )
        if interval is None:
            k_b, k_n = np.nan, np.nan
            b_count = n_count = 0
            interval_label = "нет данных"
        else:
            vna_start, vna_end, vna_count = interval
            regression_mask = (
                np.isfinite(vna_p)
                & (vna_p >= vna_start)
                & (vna_p < vna_end)
            )
            k_b, _, b_count = _ols(
                b_p[regression_mask], tau[regression_mask]
            )
            k_n, _, n_count = _ols(
                power_p[regression_mask], tau[regression_mask]
            )
            interval_label = (
                f"{vna_start:.0f}–{vna_end:.0f} % ({vna_count})"
            )

        # Потери суммируются по всему рабочему времени периода. Порог ВНА
        # берётся из распределения принятых периодов, а выбросы bприв и температуры
        # отбрасываются теми же физическими ограничениями, что и раньше.
        temperature_ok = ~np.isfinite(temperature_p) | (
            (temperature_p > T_MIN) & (temperature_p < T_MAX)
        )
        power_limit = (
            power_threshold if np.isfinite(power_threshold) else LOW_POWER
        )
        working_quality = (
            np.isfinite(power_p)
            & (power_p >= power_limit)
            & np.isfinite(b_p)
            & (b_p > B_MIN)
            & (b_p < B_MAX)
            & temperature_ok
        )
        vna_quality = np.isfinite(vna_p) & (vna_p >= vna_threshold)
        loss_quality = working_quality & vna_quality

        # Рост bприв означает перерасход топлива. Снижение Nприв означает
        # недовыработку. Поэтому в экономике берём только положительную
        # величину соответствующей потери; знаковые дельты отчёта не меняются.
        fuel_loss_rate = np.where(
            np.isfinite(k_b) & loss_quality,
            np.clip(k_b * tau, 0.0, None) * power_p,
            0.0,
        )
        power_loss_rate = np.where(
            np.isfinite(k_n) & loss_quality,
            np.clip(-k_n * tau, 0.0, None),
            0.0,
        )

        # Эти же получасовые величины можно записать в итоговый лист «Данные».
        # Их парные средние дают прежние итоги; метод расчёта не меняется.
        row_losses.extend({
            "date": dates.iloc[index],
            "period": period_number,
            "fuel_loss_rate": float(fuel_rate),
            "power_loss_rate": float(power_rate),
        } for index, fuel_rate, power_rate in zip(
            order, fuel_loss_rate, power_loss_rate
        ))

        fuel_nm3 = _hourly_mean_sum(fuel_loss_rate)
        power_mwh = _hourly_mean_sum(power_loss_rate)
        gas_rub = fuel_nm3 * float(gas_price_rub_per_m3)
        electricity_rub = power_mwh * electricity_margin

        periods.append({
            "Период": period_number,
            "Начало": pd.Timestamp(period_row.date_start),
            "Конец": pd.Timestamp(period_row.date_end),
            "Недовыработка, МВт·ч": power_mwh,
            "Недовыработка, руб": electricity_rub,
            "Перерасход, нм³": fuel_nm3,
            "Перерасход, руб": gas_rub,
            "Общие издержки, руб": electricity_rub + gas_rub,
            "k_Nприв": k_n,
            "k_bприв": k_b,
            "точек регрессии N": n_count,
            "точек регрессии b": b_count,
            "VNA-интервал регрессии": interval_label,
        })

    if delta_table is not None:
        if {"Часы начала", "Часы конца"}.issubset(delta_table.columns):
            durations = pd.to_numeric(delta_table["Часы конца"], errors="coerce") - pd.to_numeric(
                delta_table["Часы начала"], errors="coerce"
            )
            period_durations = durations.to_list()
    total_period_hours = (
        float(sum(period_durations))
        if period_durations and all(np.isfinite(value) and value > 0 for value in period_durations)
        else np.nan
    )
    annual_factor = ANNUAL_HOURS / total_period_hours if np.isfinite(total_period_hours) else np.nan
    annualized = {
        "fuel_overrun_nm3": np.nan,
        "fuel_overrun_rub": np.nan,
        "underproduction_mwh": np.nan,
        "underproduction_rub": np.nan,
        "total_cost_rub": np.nan,
    }

    table = pd.DataFrame(periods)
    if table.empty:
        table = pd.DataFrame(columns=ECONOMICS_COLUMNS)
    else:
        total = {column: np.nan for column in ECONOMICS_COLUMNS}
        total["Период"] = "ИТОГО"
        for column in (
            "Недовыработка, МВт·ч",
            "Недовыработка, руб",
            "Перерасход, нм³",
            "Перерасход, руб",
            "Общие издержки, руб",
        ):
            total[column] = float(
                pd.to_numeric(table[column], errors="coerce").sum()
            )
        annualized = {
            "fuel_overrun_nm3": total["Перерасход, нм³"] * annual_factor,
            "fuel_overrun_rub": total["Перерасход, руб"] * annual_factor,
            "underproduction_mwh": total["Недовыработка, МВт·ч"] * annual_factor,
            "underproduction_rub": total["Недовыработка, руб"] * annual_factor,
            "total_cost_rub": total["Общие издержки, руб"] * annual_factor,
        }
        fuel_row = {
            "Период": "Суммарные издержки, связанные с перерасходом, приведенные к году эксплуатации",
            "Перерасход, нм³": annualized["fuel_overrun_nm3"],
            "Перерасход, руб": annualized["fuel_overrun_rub"],
        }
        electricity_row = {
            "Период": "Упущенная выгода, связанная с недопоставкой электроэнергии в сеть, приведенная к году эксплуатации",
            "Недовыработка, МВт·ч": annualized["underproduction_mwh"],
            "Недовыработка, руб": annualized["underproduction_rub"],
        }
        total_cost_row = {
            "Период": "Суммарные издержки, приведенные к году эксплуатации",
            "Общие издержки, руб": annualized["total_cost_rub"],
        }
        power_label = (
            f"Наработка при Nприв ≥ {power_threshold:g} МВт"
            if np.isfinite(power_threshold) else "Наработка при пороге Nприв"
        )
        vna_nominal_threshold = nominal_hours.get("vna_threshold", np.nan)
        vna_label = (
            f"Наработка при ВНА ≥ {vna_nominal_threshold:g} %"
            if np.isfinite(vna_nominal_threshold) else "Наработка при пороге ВНА"
        )
        hours_rows = [
            {"Период": "Длительность принятых периодов", "Наработка, ч": total_period_hours},
            {"Период": power_label, "Наработка, ч": nominal_hours.get("power_hours", np.nan)},
            {"Период": vna_label, "Наработка, ч": nominal_hours.get("vna_hours", np.nan)},
        ]
        table = pd.concat(
            [table, pd.DataFrame([total, fuel_row, electricity_row, total_cost_row, *hours_rows])],
            ignore_index=True,
        )

    table = table[ECONOMICS_COLUMNS].copy()

    return {
        "table": table,
        "annualized": annualized,
        "total_period_hours": total_period_hours,
        "periods": periods,
        "row_losses": pd.DataFrame(row_losses),
        "distribution": distribution,
        "vna_threshold": vna_threshold,
        "power_threshold": float(power_threshold),
        "gas_price_rub_per_m3": float(gas_price_rub_per_m3),
        "electricity_price_rub_per_mwh": float(electricity_price_rub_per_mwh),
        "electricity_cost_rub_per_mwh": electricity_cost_rub_per_mwh,
        "electricity_margin_rub_per_mwh": electricity_margin,
    }


def print_economics(result: dict) -> None:
    """Печатает экономическую таблицу и параметры расчёта в лог."""

    print()
    print("=" * 90)
    print("ЭКОНОМИЧЕСКИЙ РАСЧЁТ")
    print("=" * 90)
    total_period_hours = result.get("total_period_hours", np.nan)
    if np.isfinite(total_period_hours):
        print(f"Приведение к году: {ANNUAL_HOURS:.0f} / {total_period_hours:.1f} ч по принятым периодам")
    else:
        print("Приведение к году: нет корректной длительности всех принятых периодов")
    print(
        f"Порог мощности по распределению: Nприв > "
        f"{result['power_threshold']:.1f} МВт"
    )
    vna_threshold = result["vna_threshold"]
    if np.isfinite(vna_threshold):
        print(
            "Общий порог ВНА по принятым периодам, шаг 1°: "
            f"ВНА ≥ {vna_threshold:.0f} %"
        )
    else:
        print("Общий порог ВНА: не определён — нет корректных рабочих записей")
    print(
        f"Тариф газа: {result['gas_price_rub_per_m3']:.4f} руб/нм³; "
        f"тариф электроэнергии: "
        f"{result['electricity_price_rub_per_mwh']:.2f} руб/МВт·ч; "
        f"себестоимость ЭЭ: {result['electricity_cost_rub_per_mwh']:.2f} "
        f"руб/МВт·ч; маржа: "
        f"{result['electricity_margin_rub_per_mwh']:.2f} руб/МВт·ч"
    )
    print(
        "Метод экономики: регрессия в самом частом интервале ВНА 1°; "
        "средние двух соседних получасовых потерь суммируются за весь "
        "рабочий период."
    )
    print(
        f"Фильтры качества: {B_MIN:g} < bприв < {B_MAX:g}; "
        f"{T_MIN:g} < T воздуха < {T_MAX:g} °C"
    )
    print()
    table = result["table"].copy()
    display = table[ECONOMICS_COLUMNS].copy()
    for column in (
        "Недовыработка, МВт·ч",
        "Недовыработка, руб",
        "Перерасход, нм³",
        "Перерасход, руб",
        "Общие издержки, руб",
    ):
        display[column] = pd.to_numeric(
            display[column], errors="coerce"
        ).round(3)
    display["Наработка, ч"] = pd.to_numeric(
        display["Наработка, ч"], errors="coerce"
    ).round(1)
    print(display.to_string(index=False))
    print("=" * 90)
