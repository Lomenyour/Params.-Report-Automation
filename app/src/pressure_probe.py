"""Read-only records and plot coordinates for the desktop pressure probe."""
from __future__ import annotations

import math

import matplotlib.dates as mdates
import pandas as pd


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def attach_pressure_probe(figure, axis, values):
    """Keep actual N/VNA readings together, without changing the input frame."""
    dates = pd.to_datetime(values["date"], errors="coerce")
    power = values["power_n"] if "power_n" in values else [None] * len(values)
    vna = values["vna"] if "vna" in values else [None] * len(values)
    points = []
    for date, measured_n, angle in zip(dates, power, vna):
        if pd.isna(date):
            continue
        moment = pd.Timestamp(date)
        label = moment.strftime("%d.%m.%Y %H:%M")
        if moment.second or moment.microsecond or moment.nanosecond:
            label = moment.strftime("%d.%m.%Y %H:%M:%S")
            if moment.microsecond or moment.nanosecond:
                label += "." + f"{moment.microsecond:06d}{moment.nanosecond:03d}".rstrip("0")
        if moment.tzinfo is not None:
            offset = moment.strftime("%z")
            label += f" {offset[:3]}:{offset[3:]}"
        points.append([
            float(mdates.date2num(moment.to_datetime64())), label,
            _finite(measured_n), _finite(angle),
        ])
    # Stable sorting retains the first source record for duplicate dates.
    points.sort(key=lambda point: point[0])
    figure._pressure_probe = (axis, points)


def pressure_probe_payload(figure):
    """Call after the PNG draw, so its axes and overlay have identical bounds."""
    probe = getattr(figure, "_pressure_probe", None)
    if probe is None or not probe[1]:
        return None
    axis, points = probe
    bounds = axis.get_position()
    lower, upper = axis.get_xlim()
    if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
        return None
    return {
        "bounds": [bounds.x0, 1.0 - bounds.y1, bounds.width, bounds.height],
        "x_min": float(lower), "x_max": float(upper), "points": points,
    }
