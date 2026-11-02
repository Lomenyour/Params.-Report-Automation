"""Small readers for known sensor export layouts. No interpolation or time bucketing."""
from __future__ import annotations
import csv
from functools import lru_cache
import io
import math
from pathlib import Path
import re
import pandas as pd
from unit_conversions import extract_unit

SERVICE_FIELDS = {"date", "time", "milliseconds"}
_INDEX = re.compile(r"^\[(\d+)\]\s*_?(.*)$")


def normalize_tag(value):
    text = str(value).strip()
    match = _INDEX.match(text)
    if match:
        text = match[2].lstrip("_")
    return text.strip()


def _same_value(left, right):
    if left == right:
        return True
    try:
        a, b = (float(value.replace(" ", "").replace(",", ".")) for value in (left, right))
        return math.isfinite(a) and math.isfinite(b) and a == b
    except (ValueError, TypeError, AttributeError):
        return False


def _timestamps(values):
    # Explicit formats avoid locale-dependent day/month guessing.
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if pd.api.types.is_datetime64_any_dtype(values):
        if getattr(values.dt, "tz", None) is not None:
            raise ValueError("Часовой пояс выгрузки нужно согласовать явно.")
        return pd.to_datetime(values)
    for pattern in ("%d.%m.%y %H:%M:%S:%f", "%d.%m.%Y %H:%M:%S:%f",
                    "%d.%m.%Y %H:%M:%S,%f", "%Y.%m.%d %H:%M:%S,%f",
                    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "ISO8601"):
        missing = result.isna() & values.notna()
        if not missing.any():
            break
        parsed = pd.to_datetime(values.loc[missing], format=pattern, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            raise ValueError("Часовой пояс выгрузки нужно согласовать явно.")
        result.loc[missing] = parsed
    return result


def _finish(frame, timestamp, info, layout):
    valid = timestamp.notna() & (timestamp.dt.minute % 30 == 0) & (timestamp.dt.second == 0) & (timestamp.dt.microsecond == 0) & (timestamp.dt.nanosecond == 0)
    selected = frame.loc[valid].copy()
    selected.index = pd.DatetimeIndex(timestamp.loc[valid], name="timestamp")
    if selected.index.has_duplicates:
        raise ValueError("В выбранном листе повторяются даты и время замеров.")
    if selected.empty:
        raise ValueError("В выгрузке нет получасовых замеров на :00 или :30.")
    selected = selected.sort_index()
    selected.attrs.update(channel_info=info, source_format=layout,
                          skipped_rows=int((~valid).sum()), invalid_dates=int(timestamp.isna().sum()))
    return selected


def _horizontal(table):
    definitions = {}
    header = None
    mode = None
    for index, row in table.head(100).iterrows():
        labels = [str(value).strip() if pd.notna(value) else "" for value in row]
        lower = [value.casefold() for value in labels]
        if {"date", "time"} <= set(lower):
            header, mode = index, "date/time"
            break
        if lower and lower[0] in {"время", "дата", "дата и время", "дата/время"} and any(labels[1:]):
            header, mode = index, "single timestamp"
            break
        if labels:
            match = re.match(r"^\[(\d+)\]\s+(\S+)\s+_\S+\s+(.*)$", labels[0])
            if match:
                definitions[int(match[1])] = (match[2], match[3])
    if header is None:
        raise ValueError("Не найдена таблица датчиков: нужны date/time либо колонка «Время»/«Дата и время».")
    labels = list(table.loc[header])
    keep, names, info = [], [], {}
    for position, value in enumerate(labels):
        if pd.isna(value) or not str(value).strip():
            continue
        original = str(value).strip()
        if mode == "single timestamp" and position == 0:
            name = "date"
        elif original.casefold() in SERVICE_FIELDS:
            name = original.casefold()
        else:
            match = _INDEX.match(original)
            definition = definitions.get(int(match[1])) if match else None
            name = normalize_tag(original)
            if definition:
                expected, description = definition
                if name != expected and not re.fullmatch(re.escape(expected) + r"\.\d+", name):
                    raise ValueError(f"Тег в заголовке {original} противоречит описанию {expected}.")
                name = expected
            else:
                description = ""
            info[name] = {"code": name, "description": description, "unit": extract_unit(description), "source_header": original}
        if name in names:
            raise ValueError(f"В выгрузке повторяется тег/поле {name}.")
        names.append(name)
        keep.append(position)
    frame = table.loc[header + 1:, keep].copy()
    frame.columns = names
    frame = frame.dropna(how="all")
    if mode == "date/time":
        dates = _timestamps(frame["date"])
        delta = pd.to_timedelta(frame["time"].astype(str), errors="coerce")
        timestamp = dates.dt.normalize() + delta
        if "milliseconds" in frame:
            timestamp += pd.to_timedelta(pd.to_numeric(frame["milliseconds"], errors="coerce"), unit="ms")
    else:
        timestamp = _timestamps(frame["date"])
    return _finish(frame, timestamp, info, mode)


def _csv(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not any(any(re.fullmatch(r"Тег\s*\d+", cell.strip(), flags=re.I) for cell in row) for row in rows):
        return _horizontal(pd.DataFrame(rows).replace("", None))
    metadata, columns, records, info = {}, {}, {}, {}
    for row in rows:
        if len(row) > 18 and row[1].strip().isdigit() and row[3].strip():
            metadata[int(row[1])] = (normalize_tag(row[3]), row[7].strip(), row[18].strip())
        if "Время" in [cell.strip() for cell in row]:
            columns = {}
            for index, cell in enumerate(row):
                match = re.fullmatch(r"Тег\s*(\d+)", cell.strip(), flags=re.I)
                if match:
                    number = int(match[1])
                    if number not in metadata:
                        raise ValueError(f"В CSV отсутствует описание Тег{number}.")
                    code, description, unit = metadata[number]
                    if code in info and info[code]["unit"] and unit and info[code]["unit"].casefold() != unit.casefold():
                        raise ValueError(f"В CSV противоречивые единицы канала {code}.")
                    if code in columns.values():
                        raise ValueError(f"Повторный тег {code} в странице CSV.")
                    columns[index] = code
                    info[code] = dict(code=code, description=description, unit=unit, source_header=cell)
            continue
        if not columns or len(row) < 2:
            continue
        from datetime import datetime
        try:
            timestamp = pd.Timestamp(datetime.strptime(row[1].strip(), "%Y.%m.%d %H:%M:%S,%f"))
        except ValueError:
            continue
        record = records.setdefault(timestamp, {"date": timestamp})
        for index, code in columns.items():
            value = row[index].strip() if index < len(row) else ""
            if not value:
                continue
            if code in record and not _same_value(record[code], value):
                raise ValueError(f"В CSV конфликт значений {code} на {timestamp}.")
            record[code] = value
    if not records:
        raise ValueError("В CSV не найдены строки данных.")
    frame = pd.DataFrame(records.values())
    return _finish(frame, pd.to_datetime(frame["date"]), info, "CSV SPPA-T3000")


def _read(path, sheet):
    if Path(path).suffix.casefold() == ".csv":
        return _csv(path)
    with pd.ExcelFile(path, engine="calamine") as book:
        table = book.parse(sheet, header=None)
    return _horizontal(table)


@lru_cache(maxsize=3)
def _cached(path, sheet, modified, size):
    return _read(path, sheet)


def read_sensor_sheet(path, sheet):
    path = Path(path)
    if path.exists():
        stat = path.stat()
        result = _cached(str(path.resolve()), sheet, stat.st_mtime_ns, stat.st_size)
    else:
        result = _read(path, sheet)  # Also supports isolated in-memory test adapters.
    return result.copy(deep=True)
