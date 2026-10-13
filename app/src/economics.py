# -*- coding: utf-8 -*-
"""Расчёт экономических потерь по периодам работы ГТУ.

Модуль содержит только фактическую часть методики:

* перерасход топлива из наклона регрессии bприв по часам;
* недовыработку электроэнергии из наклона регрессии Nприв по часам;
* перевод натуральных величин в рубли по тарифам, введённым пользователем;
* сводную таблицу по периодам и строку ИТОГО.

Порог мощности берётся из общего распределения мощности и правила 80 %
рабочих записей, а порог ВНА — из общего распределения ВНА с шагом 1°.
Оба порога одинаковы для всех периодов данного прогона.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from periods import LOW_POWER


# Входные данные идут с шагом 30 минут.
DT_HOURS = 0.5
HOURLY_WINDOW = 3
HOURLY_STEP = 2

# Принятые фильтры качества измерений. Границы сохраняем строгими, как в
# исходной методике: выбросы на самих границах не проходят.
B_MIN, B_MAX = 150.0, 600.0
T_MIN, T_MAX = -40.0, 50.0

# Распределение ВНА для экономики: целые проценты, верхние интервалы до 80 %
# рабочего времени.
VNA_BIN_WIDTH = 1.0
WORKING_SHARE = 0.80


ECONOMICS_COLUMNS = [
    "Период",
    "Начало",
    "Конец",
    "Недовыработка, МВт·ч",
    "Недовыработка, руб",
    "Перерасход, нм³",
    "Перерасход, руб",
    "Общие издержки, руб",
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
    """Интегрирует поток по часовым окнам из трёх получасовых точек."""

    values = np.asarray(values, dtype=float)
    total = 0.0
    for start in range(0, len(values) - HOURLY_WINDOW + 1, HOURLY_STEP):
        mean = np.nanmean(values[start:start + HOURLY_WINDOW])
        if np.isfinite(mean) and mean > 0.0:
            total += float(mean)
    return total


def _working_mask(data: pd.DataFrame) -> np.ndarray:
    power = _num(data, "power")
    return np.isfinite(power) & (power > LOW_POWER)


def build_vna_distribution(data: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    """Строит единое распределение ВНА по всей книге и выбирает порог.

    Остановы исключаются по LOW_POWER. Начиная с верхних интервалов ВНА,
    выбирается набор, содержащий не менее 80 % рабочих записей. Нижняя
    граница последнего добавленного интервала становится порогом; рабочее
    условие далее задаётся строго как ВНА > threshold.
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


def calculate_economics(
    data: pd.DataFrame,
    periods_df: pd.DataFrame,
    gas_price_rub_per_m3: float,
    electricity_price_rub_per_mwh: float,
    power_threshold: float,
    vna_data: pd.DataFrame | None = None,
) -> dict:
    """Считает натуральные и денежные потери по каждому периоду.

    power_threshold передаётся из уже выполненного общего распределения
    мощности в RH. Порог ВНА рассчитывается здесь один раз по всей книге.
    """

    combined = _merge_vna(data, vna_data)
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

    periods = []
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
        if np.isfinite(power_threshold):
            nominal_quality = _power_quality_mask(
                power_p, b_p, temperature_p, power_threshold
            )
        else:
            nominal_quality = np.zeros(len(order), dtype=bool)
        vna_quality = np.isfinite(vna_p) & (vna_p > vna_threshold)
        combined_quality = nominal_quality & vna_quality

        k_b, _, b_count = _ols(
            b_p[combined_quality], tau[combined_quality]
        )
        k_n, _, n_count = _ols(
            power_p[combined_quality], tau[combined_quality]
        )

        # Рост bприв означает перерасход топлива. Снижение Nприв означает
        # недовыработку. Поэтому в экономике берём только положительную
        # величину соответствующей потери; знаковые дельты отчёта не меняются.
        fuel_loss_rate = np.where(
            np.isfinite(k_b) & combined_quality,
            np.clip(k_b * tau, 0.0, None) * power_p,
            0.0,
        )
        power_loss_rate = np.where(
            np.isfinite(k_n) & combined_quality,
            np.clip(-k_n * tau, 0.0, None),
            0.0,
        )

        fuel_nm3 = _hourly_mean_sum(fuel_loss_rate)
        power_mwh = _hourly_mean_sum(power_loss_rate)
        gas_rub = fuel_nm3 * float(gas_price_rub_per_m3)
        electricity_rub = power_mwh * float(electricity_price_rub_per_mwh)

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
        })

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
        table = pd.concat([table, pd.DataFrame([total])], ignore_index=True)

    table = table[ECONOMICS_COLUMNS].copy()

    return {
        "table": table,
        "periods": periods,
        "distribution": distribution,
        "vna_threshold": vna_threshold,
        "power_threshold": float(power_threshold),
        "gas_price_rub_per_m3": float(gas_price_rub_per_m3),
        "electricity_price_rub_per_mwh": float(electricity_price_rub_per_mwh),
    }


def print_economics(result: dict) -> None:
    """Печатает экономическую таблицу и параметры расчёта в лог."""

    print()
    print("=" * 90)
    print("ЭКОНОМИЧЕСКИЙ РАСЧЁТ")
    print("=" * 90)
    print(
        f"Порог мощности по распределению: Nприв > "
        f"{result['power_threshold']:.1f} МВт"
    )
    vna_threshold = result["vna_threshold"]
    if np.isfinite(vna_threshold):
        print(
            "Общий порог ВНА по распределению с шагом 1°: "
            f"ВНА > {vna_threshold:.0f} %"
        )
    else:
        print("Общий порог ВНА: не определён — нет корректных рабочих записей")
    print(
        f"Тариф газа: {result['gas_price_rub_per_m3']:.4f} руб/нм³; "
        f"тариф электроэнергии: "
        f"{result['electricity_price_rub_per_mwh']:.2f} руб/МВт·ч"
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
    print(display.to_string(index=False))
    print("=" * 90)

