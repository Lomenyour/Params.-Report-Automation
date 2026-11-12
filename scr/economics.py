"""Потери по местным порогам каждого периода и пригодным получасовым строкам."""
from __future__ import annotations

import numpy as np
import pandas as pd

from periods import LOW_POWER

DT_HOURS = 0.5
B_MIN, B_MAX = 150.0, 600.0
T_MIN, T_MAX = -40.0, 50.0
VNA_BIN_WIDTH = 1.0
WORKING_SHARE = .80
ANNUAL_HOURS = 8760.0
POWER_HOURS = 'Учтено для недовыработки, ч'
FUEL_HOURS = 'Учтено для перерасхода, ч'
ECONOMICS_COLUMNS = [
    'Период', 'Начало', 'Конец', 'Недовыработка, МВт·ч', 'Недовыработка, руб',
    'Перерасход, нм³', 'Перерасход, руб', 'Общие издержки, руб', 'Наработка, ч',
    'Порог Nприв, МВт', 'Порог ВНА, %', POWER_HOURS, FUEL_HOURS, 'Статус расчёта',
]


def _num(data, name):
    if name not in data:
        return np.full(len(data), np.nan)
    return pd.to_numeric(data[name], errors='coerce').to_numpy(dtype=float)


def _bpriv(data):
    b, fuel, power = (_num(data, key) for key in ('fuel_specific', 'fuel', 'power'))
    with np.errstate(divide='ignore', invalid='ignore'):
        derived = fuel / power
    return np.where(np.isfinite(b), b, derived)


def _ambient_temperature(data):
    for key in ('ambient_temperature', 'Токр.воздуха', 't'):
        if key in data:
            return _num(data, key)
    return np.full(len(data), np.nan)


def _ols(y, x):
    y, x = np.asarray(y, dtype=float), np.asarray(x, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 2 or np.unique(x[valid]).size < 2:
        return np.nan, np.nan, int(valid.sum())
    slope, intercept = np.polyfit(x[valid], y[valid], 1)
    return float(slope), float(intercept), int(valid.sum())


def _working_mask(data):
    power = _num(data, 'power')
    return np.isfinite(power) & (power > LOW_POWER)


def build_vna_distribution(data):
    """Верхние целые интервалы ВНА до покрытия 80 % рабочих записей."""
    vna = _num(data, 'vna')
    valid = _working_mask(data) & np.isfinite(vna) & (vna >= 0) & (vna <= 100)
    counts, edges = np.histogram(vna[valid], bins=np.arange(0., 101., VNA_BIN_WIDTH))
    total = int(counts.sum())
    cumulative = np.cumsum(counts[::-1])[::-1]
    distribution = pd.DataFrame({
        'ВНА от, %': edges[:-1], 'ВНА до, %': edges[1:], 'Записей': counts,
        'Доля, %': counts / total * 100 if total else np.zeros(len(counts)),
        'Накопленная доля сверху, %': cumulative / total * 100 if total else np.zeros(len(counts)),
    })
    eligible = np.flatnonzero(cumulative >= total * WORKING_SHARE) if total else []
    return distribution, float(edges[eligible[-1]]) if len(eligible) else None


def _dominant_vna_interval(data):
    if data.empty:
        return None
    values = _num(data, 'vna')
    values = values[np.isfinite(values) & (values >= 0) & (values <= 100)]
    if not values.size:
        return None
    counts = pd.Series(np.floor(values).astype(int).clip(max=99)).value_counts()
    start = int(counts.index[0])
    return float(start), float(start + 1), int(counts.iloc[0])


def _period_mask(data, number, row):
    if 'period' in data:
        return _num(data, 'period') == number
    return pd.to_datetime(data['date']).between(row.date_start, row.date_end).to_numpy()


def _merge_vna(data, vna_data):
    result = data.copy()
    if 'vna' in result and pd.to_numeric(result.vna, errors='coerce').notna().any():
        return result
    if vna_data is None or 'vna' not in vna_data:
        result['vna'] = np.nan
        return result
    right = vna_data[['date', 'vna']].copy()
    right['date'] = pd.to_datetime(right.date, errors='coerce')
    if right.date.duplicated().any():
        raise ValueError('Повторяющиеся даты в данных ВНА для экономики.')
    result['date'] = pd.to_datetime(result.date, errors='coerce')
    return result.drop(columns=['vna'], errors='ignore').merge(right, on='date', how='left', sort=False)


def _strict_sum(values):
    values = np.asarray(values, dtype=float)
    return float(values.sum()) if len(values) and np.isfinite(values).all() else np.nan


def _common_threshold(periods, key):
    values = [row[key] for row in periods]
    return values[0] if values and np.isfinite(values).all() and len(set(values)) == 1 else np.nan


def calculate_economics(data, periods_df, gas_price_rub_per_m3,
                        electricity_price_rub_per_mwh, power_threshold=None,
                        vna_data=None, electricity_cost_rub_per_mwh=0.,
                        delta_table=None, nominal_hours=None):
    """Своё окно режима/часы для каждого периода и каждого вида потерь.

    power_threshold/nominal_hours оставлены для совместимости вызывающего
    кода; глобальные пороги не управляют экономическими выборками.
    delta_table используется только для справочной длительности периодов.
    """
    from RH_raschet import build_power_distribution

    combined = _merge_vna(data, vna_data)
    combined['date'] = pd.to_datetime(combined['date'], errors='coerce')
    if combined.date.isna().any():
        raise ValueError('Для построчной экономики нужны корректные даты всех строк.')
    if combined.date.duplicated().any():
        raise ValueError('Для построчной экономики недопустимы повторяющиеся даты.')
    price = float(gas_price_rub_per_m3)
    electricity_price = float(electricity_price_rub_per_mwh)
    electricity_cost = float(electricity_cost_rub_per_mwh)
    if not np.isfinite([price, electricity_price, electricity_cost]).all():
        raise ValueError('Для экономики нужны конечные числовые тарифы.')
    margin = electricity_price - electricity_cost
    periods, row_losses, distributions, durations = [], [], [], []
    for row in periods_df.itertuples(index=False):
        number = int(row.period)
        part = combined.loc[_period_mask(combined, number, row)].sort_values('date', kind='stable').copy()
        if part.empty:
            # An accepted period with no observations must not disappear from totals.
            part = combined.iloc[:0].copy()
        dates = pd.DatetimeIndex(part.date)
        if len(dates) and ((dates < row.date_start) | (dates > row.date_end)).any():
            raise ValueError(f'Экономика: строки периода {number} выходят за его границы.')
        gaps = np.diff(dates.as_unit('ns').asi8)
        step_ns = int(pd.Timedelta(minutes=30).value)
        if np.any(gaps % step_ns):
            raise ValueError(f'Экономика: шаг дат периода {number} не кратен 30 минутам.')
        hours = _num(part, 'hours')
        finite_hours = hours[np.isfinite(hours)]
        if np.any(np.diff(finite_hours) <= 0):
            raise ValueError(f'Экономика: счётчик часов периода {number} должен возрастать.')
        tau = hours - hours[0] if len(hours) else hours
        durations.append(float(hours[-1] - hours[0]) if len(hours) else np.nan)
        power, b, vna = _num(part, 'power'), _bpriv(part), _num(part, 'vna')
        temperature = _ambient_temperature(part)
        working = np.isfinite(power) & (power > LOW_POWER)
        power_distribution, n_limit = build_power_distribution(part.loc[working])
        vna_distribution, vna_limit = build_vna_distribution(part)
        n_limit = np.nan if n_limit is None else float(n_limit)
        vna_limit = np.nan if vna_limit is None else float(vna_limit)
        for name, table in (('power', power_distribution), ('vna', vna_distribution)):
            table = table.copy(); table.insert(0, 'Период', number)
            distributions.append((name, table))
        vna_valid = np.isfinite(vna) & (vna >= 0) & (vna <= 100)
        temperature_ok = np.isnan(temperature) | ((temperature > T_MIN) & (temperature < T_MAX))
        time_ok = np.isfinite(tau) & (tau >= 0)
        power_quality = working & vna_valid & temperature_ok & time_ok
        fuel_quality = power_quality & np.isfinite(b) & (b > B_MIN) & (b < B_MAX)
        # Keep the established dominant 1 pp regression regime, independently
        # of the nominal thresholds used for the loss numerator/denominator.
        interval = _dominant_vna_interval(part.loc[power_quality])
        in_interval = np.zeros(len(part), dtype=bool)
        interval_label = 'нет данных'
        if interval is not None:
            left, right, count = interval
            in_interval = (vna >= left) & ((vna < right) | ((right == 100) & (vna == 100)))
            interval_label = f'{left:.0f}–{right:.0f} % ({count})'
        k_n, _, n_count = _ols(power[power_quality & in_interval], tau[power_quality & in_interval])
        k_b, _, b_count = _ols(b[fuel_quality & in_interval], tau[fuel_quality & in_interval])
        thresholds_known = np.isfinite(n_limit) and np.isfinite(vna_limit)
        regime = working & vna_valid & (power >= n_limit) & (vna >= vna_limit)
        n_mask, b_mask = regime & power_quality, regime & fuel_quality
        n_hours, b_hours = float(n_mask.sum() * DT_HOURS), float(b_mask.sum() * DT_HOURS)

        def losses(slope, eligible, fuel=False):
            rates = np.zeros(len(part), dtype=float)
            # Unavailable observations stay distinguishable from a valid zero.
            rates[~np.isfinite(power) | (working & (~vna_valid | ~time_ok | ~temperature_ok))] = np.nan
            rates[regime & ~eligible] = np.nan
            available = thresholds_known and np.isfinite(slope) and eligible.any()
            if available:
                rates[eligible] = np.maximum((slope if fuel else -slope) * tau[eligible], 0.)
                if fuel:
                    rates[eligible] *= power[eligible]
                quantity = float(rates[eligible].sum() * DT_HOURS)
                status = 'рассчитано'
            else:
                rates[working if not thresholds_known else regime] = np.nan
                quantity, status = np.nan, 'нет данных'
            return rates, quantity, status

        n_rates, n_mwh, n_status = losses(k_n, n_mask)
        b_rates, b_nm3, b_status = losses(k_b, b_mask, fuel=True)
        n_money, b_money = n_mwh * margin, b_nm3 * price
        quality = dict(rows=len(part), gap_count=int((gaps > step_ns).sum()),
            missing_half_hours=int(np.maximum(gaps // step_ns - 1, 0).sum()),
            invalid_power=int((~np.isfinite(power)).sum()),
            invalid_vna=int((~vna_valid).sum()), invalid_b=int((~np.isfinite(b) | (b <= B_MIN) | (b >= B_MAX)).sum()),
            invalid_temperature=int((~temperature_ok).sum()), missing_temperature=int(np.isnan(temperature).sum()),
            invalid_hours=int((~time_ok).sum()), timezone=str(dates.tz) if dates.tz else None)
        period = {
            'Период': number, 'Начало': pd.Timestamp(row.date_start), 'Конец': pd.Timestamp(row.date_end),
            'Недовыработка, МВт·ч': n_mwh, 'Недовыработка, руб': n_money,
            'Перерасход, нм³': b_nm3, 'Перерасход, руб': b_money, 'Общие издержки, руб': n_money + b_money,
            'Порог Nприв, МВт': n_limit, 'Порог ВНА, %': vna_limit,
            POWER_HOURS: n_hours, FUEL_HOURS: b_hours,
            'Статус расчёта': f'Мощность: {n_status}; газ: {b_status}',
            'k_Nприв': k_n, 'k_bприв': k_b, 'точек регрессии N': n_count,
            'точек регрессии b': b_count, 'VNA-интервал регрессии': interval_label, 'quality': quality,
        }
        periods.append(period)
        for index, date in enumerate(dates):
            row_losses.append(dict(date=date, period=number, tau_hours=float(tau[index]),
                power_threshold=n_limit, vna_threshold=vna_limit,
                power_eligible=bool(n_mask[index]), fuel_eligible=bool(b_mask[index]),
                power_loss_rate=float(n_rates[index]), fuel_loss_rate=float(b_rates[index]),
                power_loss_mwh=float(n_rates[index] * DT_HOURS),
                fuel_loss_nm3=float(b_rates[index] * DT_HOURS)))

    total = {'Период': 'ИТОГО'}
    quantities = ('Недовыработка, МВт·ч', 'Недовыработка, руб', 'Перерасход, нм³', 'Перерасход, руб', 'Общие издержки, руб')
    for key in quantities:
        total[key] = _strict_sum([part[key] for part in periods])
    n_hours = float(sum(part[POWER_HOURS] for part in periods))
    b_hours = float(sum(part[FUEL_HOURS] for part in periods))
    total.update({POWER_HOURS: n_hours, FUEL_HOURS: b_hours,
                  'Статус расчёта': 'рассчитано' if all(np.isfinite(total[k]) for k in quantities) else 'есть недоступные результаты'})
    annualized = {}
    for name, key, denominator in (
        ('underproduction_mwh', 'Недовыработка, МВт·ч', n_hours),
        ('underproduction_rub', 'Недовыработка, руб', n_hours),
        ('fuel_overrun_nm3', 'Перерасход, нм³', b_hours),
        ('fuel_overrun_rub', 'Перерасход, руб', b_hours),
    ):
        annualized[name] = total[key] * ANNUAL_HOURS / denominator if denominator > 0 else np.nan
    annualized['total_cost_rub'] = annualized['underproduction_rub'] + annualized['fuel_overrun_rub']
    if delta_table is not None and {'Часы начала', 'Часы конца'} <= set(delta_table.columns):
        durations = (pd.to_numeric(delta_table['Часы конца'], errors='coerce') -
                     pd.to_numeric(delta_table['Часы начала'], errors='coerce')).tolist()
    total_period_hours = _strict_sum(durations)
    extras = [total,
        {'Период': 'Суммарные издержки, связанные с перерасходом, приведенные к году эксплуатации',
         'Перерасход, нм³': annualized['fuel_overrun_nm3'], 'Перерасход, руб': annualized['fuel_overrun_rub']},
        {'Период': 'Упущенная выгода, связанная с недопоставкой электроэнергии в сеть, приведенная к году эксплуатации',
         'Недовыработка, МВт·ч': annualized['underproduction_mwh'], 'Недовыработка, руб': annualized['underproduction_rub']},
        {'Период': 'Суммарные издержки, приведенные к году эксплуатации', 'Общие издержки, руб': annualized['total_cost_rub']},
        {'Период': 'Длительность принятых периодов', 'Наработка, ч': total_period_hours},
        {'Период': 'Учтённые часы недовыработки: местные пороги и качество', 'Наработка, ч': n_hours},
        {'Период': 'Учтённые часы перерасхода: местные пороги и качество', 'Наработка, ч': b_hours},
    ] if periods else []
    table = pd.DataFrame(periods + extras).reindex(columns=ECONOMICS_COLUMNS)
    return dict(table=table, annualized=annualized, total_period_hours=total_period_hours,
        annualization_hours={'underproduction': n_hours, 'fuel': b_hours}, periods=periods,
        row_losses=pd.DataFrame(row_losses),
        distribution=pd.concat([table for name, table in distributions if name == 'vna'], ignore_index=True) if distributions else pd.DataFrame(),
        power_distributions=pd.concat([table for name, table in distributions if name == 'power'], ignore_index=True) if distributions else pd.DataFrame(),
        vna_threshold=_common_threshold(periods, 'Порог ВНА, %'),
        power_threshold=_common_threshold(periods, 'Порог Nприв, МВт'),
        gas_price_rub_per_m3=price, electricity_price_rub_per_mwh=electricity_price,
        electricity_cost_rub_per_mwh=electricity_cost, electricity_margin_rub_per_mwh=margin,
        method='period_thresholds_half_hour_v2')


def print_economics(result):
    print('\n' + '=' * 90)
    print('ЭКОНОМИКА: местные пороги каждого периода; каждая пригодная строка × 0,5 ч.')
    print('Годовой знаменатель — учтённые часы соответствующего вида потерь.')
    for period in result['periods']:
        quality = period['quality']
        print(f'Период {period["Период"]}: Nприв ≥ {period["Порог Nприв, МВт"]:g} МВт; '
              f'ВНА ≥ {period["Порог ВНА, %"]:g} %; {period["Статус расчёта"]}.')
        print(f'  Контроль: {quality}')
    display = result['table'].copy()
    numeric = display.select_dtypes(include='number').columns
    display[numeric] = display[numeric].round(3)
    print(display.to_string(index=False, na_rep='—'))
    print('=' * 90)
