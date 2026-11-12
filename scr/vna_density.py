"""Exact maximum plotted-point pair per VNA window, with >= 2/3 period span."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from VNA_full import MAX_DELTA_T, MAX_DELTA_P, MAX_DELTA_ETA, TOP_INTERVALS, _build_pair_result

PAIR_COLUMNS = ['date_1', 't_1', 'p_1', 'vna_1', 'tkk_1', 'pi_k_1', 'eta_1',
                'date_2', 't_2', 'p_2', 'vna_2', 'tkk_2', 'pi_k_2', 'eta_2',
                'delta_t', 'delta_p', 'delta_days', 'delta_eta']
COLUMNS = ['rank', 'vna_interval', 'plot_points', 'count', 'share_percent'] + PAIR_COLUMNS


class _Ranges:
    """Inclusive numeric ranges as exact row bitsets, with bounded query cache."""
    def __init__(self, values, valid):
        masks = {}
        for index in np.flatnonzero(valid):
            value = float(values[index])
            masks[value] = masks.get(value, 0) | (1 << int(index))
        self.lower, self.upper = {}, {}
        prefix = 0
        for value in sorted(masks):
            self.lower[value] = prefix
            prefix |= masks[value]
            self.upper[value] = prefix

    def between(self, first, second):
        low, high = sorted((float(first), float(second)))
        return self.upper[high] ^ self.lower[low]


def density_period_top10(values, period_number, date_start, date_end):
    """Search all admissible pairs, retaining one optimum for each window.

    Repeated raw (VNA cell, t, p, eta) groups need only their date extremes:
    every pair between two such groups gives the same plotted box in every
    eligible window. Longer date separation dominates shorter pairs.
    Projection counts and the number of valid window rows are upper bounds,
    so pruning cannot remove a better pair. No candidate-count heuristic is used.
    """
    required = {'date', 'vna', 't', 'p', 'eta_compressor', 'pi_k', 'tkk'}
    missing = sorted(required - set(values.columns))
    if missing:
        raise ValueError('Для алгоритма 2 не хватает параметров: ' + ', '.join(missing))
    frame = values.copy()
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
    frame = frame.sort_values('date', kind='stable').reset_index(drop=True)
    dates = pd.DatetimeIndex(pd.to_datetime(frame['date'], errors='coerce'))
    start, end = pd.Timestamp(date_start), pd.Timestamp(date_end)
    quality = {'rows': len(frame), 'invalid_dates': int(dates.isna().sum()),
               'duplicate_dates': int(dates[dates.notna()].duplicated(keep=False).sum()),
               'timezone': str(dates.tz) if dates.tz is not None else None,
               'windows_searched': 0, 'windows_pruned': 0, 'boxes_counted': 0}

    def result(rows, reason=''):
        table = pd.DataFrame(rows, columns=COLUMNS)
        numeric = table.select_dtypes(include='number').columns
        table[numeric] = table[numeric].round(3)
        table.attrs.update(period_number=int(period_number), algorithm=2,
                           quality=quality, empty_reason=reason)
        return table

    if pd.isna(start) or pd.isna(end) or end <= start:
        return result([], 'Недостаточная длительность периода для алгоритма 2.')
    if (dates.tz is None) != (start.tzinfo is None) or (start.tzinfo is None) != (end.tzinfo is None):
        raise ValueError('Несогласованные часовые пояса границ и данных периода.')
    inside = dates.notna() & (dates >= start) & (dates <= end)
    if np.any(dates.notna() & ~inside):
        raise ValueError('Даты строк ВНА выходят за принятые границы периода.')
    date_ns = dates.as_unit('ns').asi8
    duration = int((end-start).value)
    minimum_span = (2*duration+2)//3
    quality.update(duration_days=duration/86_400_000_000_000,
                   minimum_span_days=minimum_span/86_400_000_000_000)
    raw = np.column_stack([pd.to_numeric(frame[key], errors='coerce').to_numpy(dtype=float)
                           for key in ('t', 'p', 'eta_compressor')])
    rounded = np.round(raw, 3)
    vna = pd.to_numeric(frame['vna'], errors='coerce').to_numpy(dtype=float)
    pi = pd.to_numeric(frame['pi_k'], errors='coerce').to_numpy(dtype=float)
    tkk = pd.to_numeric(frame['tkk'], errors='coerce').to_numpy(dtype=float)
    in_vna = np.isfinite(vna) & (vna >= 0) & (vna < 100)
    valid = inside & in_vna & np.isfinite(raw).all(axis=1) & np.isfinite(pi)
    quality.update(invalid_plot_rows=int((~valid).sum()),
                   vna_outside_search=int((~in_vna).sum()),
                   eta_outside_physical_range=int((np.isfinite(raw[:, 2]) &
                       ((raw[:, 2] <= 0) | (raw[:, 2] > 100))).sum()),
                   nonpositive_pi=int((np.isfinite(pi) & (pi <= 0)).sum()))
    reason = 'Нет пар по допускам и размаху не менее 2/3 периода.'
    if valid.sum() < 2 or int(date_ns[valid].max())-int(date_ns[valid].min()) < minimum_span:
        return result([], reason)
    cells = np.searchsorted(np.arange(1001, dtype=float)/10., vna, side='right')-1
    groups = {}
    for index in np.flatnonzero(valid):
        index = int(index)
        key = (int(cells[index]), *map(float, raw[index]))
        if key not in groups:
            groups[key] = [index, index]
        elif date_ns[index] > date_ns[groups[key][1]]:
            groups[key][1] = index
    keys = list(groups)
    group_cells = np.array([key[0] for key in keys])
    group_raw = np.array([key[1:] for key in keys])
    group_round = np.round(group_raw, 3)
    extremes = np.array(list(groups.values()), dtype=int)
    first_ns, last_ns = date_ns[extremes[:, 0]], date_ns[extremes[:, 1]]
    quality['parameter_groups'] = len(keys)
    valid_bits = sum(1 << int(index) for index in np.flatnonzero(valid))
    cell_bits = [0]*1000
    for index in np.flatnonzero(in_vna):
        cell_bits[int(cells[index])] |= 1 << int(index)
    prefixes = [0]
    for bits in cell_bits:
        prefixes.append(prefixes[-1] | bits)
    windows = {}
    min_cell, max_cell = int(cells[in_vna].min()), int(cells[in_vna].max())
    for width in range(1, 11):
        for left in range(min_cell, min(max_cell, 1000-width)+1):
            mask = prefixes[left+width] ^ prefixes[left]
            if mask and mask not in windows:
                windows[mask] = (width, left)
    ranges = [_Ranges(rounded[:, axis], valid) for axis in range(3)]

    @lru_cache(maxsize=4096)
    def box_mask(a0, b0, a1, b1, a2, b2):
        return (ranges[0].between(a0, b0) & ranges[1].between(a1, b1) &
                ranges[2].between(a2, b2))

    top = {}
    ordered = sorted(windows.items(), key=lambda item:
                     (-(item[0] & valid_bits).bit_count(), *item[1]))
    for raw_window, (width, left) in ordered:
        window = raw_window & valid_bits
        potential = window.bit_count()
        cutoff = min(item['score'][0] for item in top.values()) if len(top) == TOP_INTERVALS else 0
        if potential < max(2, cutoff):
            quality['windows_pruned'] += 1
            continue
        active = np.flatnonzero((group_cells >= left) & (group_cells < left+width))
        if not active.size or int(last_ns[active].max())-int(first_ns[active].min()) < minimum_span:
            continue
        quality['windows_searched'] += 1
        indices = np.flatnonzero(valid & (cells >= left) & (cells < left+width))
        lows, highs = [], []
        for axis in range(3):
            sorted_values = np.sort(rounded[indices, axis])
            lows.append(np.searchsorted(sorted_values, group_round[active, axis], side='left'))
            highs.append(np.searchsorted(sorted_values, group_round[active, axis], side='right'))
        lows, highs = np.array(lows), np.array(highs)
        first_order = np.argsort(first_ns[active], kind='stable')
        last_order = np.argsort(last_ns[active], kind='stable')
        ordered_first = first_ns[active[first_order]]
        ordered_last = last_ns[active[last_order]]
        best, best_score = None, (max(1, cutoff-1), -1, float('-inf'), 0, 0)
        # Larger possible boxes first are only an ordering choice; every
        # remaining pair whose rigorous bound can win is still inspected.
        anchor_order = sorted(range(len(active)), key=lambda k:
                              -int(np.maximum(highs[:, k], potential-lows[:, k]).sum()))
        for position in anchor_order:
            anchor = active[position]
            after = last_order[np.searchsorted(ordered_last, int(first_ns[anchor])+minimum_span):]
            before = first_order[:np.searchsorted(ordered_first, int(last_ns[anchor])-minimum_span, side='right')]
            partners = (np.union1d(after, before) if after.size and before.size else
                        after if after.size else before)
            partners = partners[active[partners] >= anchor]
            if not partners.size:
                continue
            difference = np.abs(group_raw[active[partners]]-group_raw[anchor])
            eligible = (
                (np.round(difference[:, 0], 12) <= MAX_DELTA_T) &
                (np.round(difference[:, 1], 12) <= MAX_DELTA_P) &
                (np.round(difference[:, 2], 12) < MAX_DELTA_ETA))
            bounds = (np.maximum(highs[:, partners], highs[:, position, None])-
                      np.minimum(lows[:, partners], lows[:, position, None])).min(axis=0)
            order = np.flatnonzero(eligible & (bounds >= best_score[0]))
            order = order[np.argsort(-bounds[order], kind='stable')]
            for candidate in order:
                if bounds[candidate] < best_score[0]:
                    break
                partner_position = partners[candidate]
                partner = active[partner_position]
                alternatives = [tuple(sorted((int(extremes[anchor, 0]), int(extremes[partner, 1])))),
                                tuple(sorted((int(extremes[partner, 0]), int(extremes[anchor, 1]))))]
                i, j = min(alternatives, key=lambda pair:
                           (-(int(date_ns[pair[1]])-int(date_ns[pair[0]])), *pair))
                span = int(date_ns[j])-int(date_ns[i])
                eta_difference = float(difference[candidate, 2])
                tie = (span, -eta_difference, -i, -j)
                if bounds[candidate] == best_score[0] and tie <= best_score[1:]:
                    continue
                a, b = group_round[anchor], group_round[partner]
                box = box_mask(a[0], b[0], a[1], b[1], a[2], b[2]) & window
                quality['boxes_counted'] += 1
                count = box.bit_count()
                score = (count, *tie)
                if count >= 2 and score > best_score:
                    best_score, best = score, (i, j, box)
        if best is None:
            continue
        i, j, mask = best
        pair = _build_pair_result(dates, raw[:, 0], raw[:, 1], vna, tkk, pi, raw[:, 2], i, j)
        score = (*best_score[:3], -width, -left, *best_score[3:])
        pair.update(vna_interval=f'{left/10.:.1f}-{(left+width)/10.:.1f}',
                    plot_points=best_score[0], count=raw_window.bit_count(),
                    share_percent=raw_window.bit_count()/len(frame)*100, score=score)
        if mask not in top or score > top[mask]['score']:
            top[mask] = pair
        if len(top) > TOP_INTERVALS:
            del top[min(top, key=lambda key: top[key]['score'])]
    rows = sorted(top.values(), key=lambda item: item['score'], reverse=True)
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    return result(rows, '' if rows else reason)


def calculate_density_top10(values, periods, progress=None):
    results = []
    for period in periods.itertuples(index=False):
        number = int(period.period)
        if progress:
            progress(f'ВНА: алгоритм 2, период {number} — подбор пары по числу точек…')
        part = values.loc[values['period'] == number] if 'period' in values else values.loc[
            pd.to_datetime(values['date']).between(period.date_start, period.date_end)]
        table = density_period_top10(part, number, period.date_start, period.date_end)
        results.append(table)
        if progress:
            q = table.attrs['quality']
            progress(f'ВНА, алгоритм 2, период {number}: {len(table)} вариантов; '
                     f'строк {q["rows"]}, некорректных для графика {q.get("invalid_plot_rows", 0)}, '
                     f'повторяющихся дат {q["duplicate_dates"]}; '
                     f'часовой пояс {q["timezone"] or "не задан"}.')
            if q.get('eta_outside_physical_range') or q.get('nonpositive_pi'):
                progress(f'Проверка качества, период {number}: КПД вне (0;100] — '
                         f'{q.get("eta_outside_physical_range", 0)}, πк ≤ 0 — '
                         f'{q.get("nonpositive_pi", 0)}. Значения не исправлялись.')
    return results
