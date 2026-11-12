"""Shared presentation checks and arrow geometry for GUI and Excel RH charts."""
import numpy as np
import pandas as pd


def window_points(values, result, prefix):
    dates = pd.to_datetime(values['date'], errors='coerce')
    return values.loc[(values['period'] == result['period'])
        & (dates >= result[f'{prefix}_window_begin'])
        & (dates <= result[f'{prefix}_window_end'])].sort_values('date', kind='stable').copy()


def power_bounds(values, result):
    """The segment actually drawn by both regressions, without extrapolation."""
    if values is None or values.empty:
        return None
    parts = [window_points(values, result, prefix) for prefix in ('start', 'end')]
    if any(part.empty for part in parts):
        return None
    power = pd.to_numeric(pd.concat([part['power'] for part in parts]), errors='coerce')
    if not np.isfinite(power).all():
        return None
    return float(power.min()), float(power.max())


def dirty_above_clean(result, bounds):
    """END is never below START on the drawn segment, for a row or whole table."""
    if bounds is None:
        return False
    try:
        ks, ke, bs, be, low, high = np.broadcast_arrays(
            *(np.asarray(result[key], dtype=float)
              for key in ('k_start', 'k_end', 'b_start', 'b_end')),
            *(np.asarray(value, dtype=float) for value in bounds))
    except (KeyError, TypeError, ValueError):
        return False
    valid = np.logical_and.reduce([np.isfinite(value) for value in (ks, ke, bs, be, low, high)])
    with np.errstate(over='ignore', invalid='ignore'):
        left = (ke - ks) * low + (be - bs)
        right = (ke - ks) * high + (be - bs)
    return (valid & (low <= high) & np.isfinite(left) & np.isfinite(right)
            & (left >= 0) & (right >= 0))


def parallel_state_arrows(result, xlim, ylim, starts, line_bounds):
    """Intersect two parallel rays from frame edges with their own regression lines.

    starts are axes fractions (x, y), with y growing upwards. No measured
    points or regression coefficients are changed by this construction.
    """
    xlow, xhigh = xlim
    ylow, yhigh = ylim
    dx, dy = xhigh - xlow, yhigh - ylow
    upper, lower = starts['end'], starts['start']
    slope = -max(1., 1.6 * abs(lower[1] - upper[1]) / max(abs(lower[0] - upper[0]), .1))
    allowed_low = max(0., (line_bounds[0] - xlow) / dx)
    allowed_high = min(1., (line_bounds[1] - xlow) / dx)
    last_complete = {}
    for factor in (1., 1.5, 2., 3., 5., 10., 20.):
        direction = slope * factor
        arrows = {}
        within = True
        for prefix in ('end', 'start'):
            x0, y0 = starts[prefix]
            k, b = result[f'k_{prefix}'], result[f'b_{prefix}']
            a, c = k * dx / dy, (k * xlow + b - ylow) / dy
            if abs(a - direction) < 1e-12:
                within = False
                break
            target_x = (y0 - direction * x0 - c) / (a - direction)
            target_y = a * target_x + c
            within &= allowed_low <= target_x <= allowed_high and 0 <= target_y <= 1
            point_x = xlow + dx * target_x
            arrows[prefix] = ((xlow + dx * x0, ylow + dy * y0), (point_x, k * point_x + b))
        if within:
            return arrows
        if len(arrows) == 2:
            last_complete = arrows
    # Manual axis overrides may hide a curve completely. Preserve the common
    # direction and exact line intersections rather than changing its values.
    return last_complete
