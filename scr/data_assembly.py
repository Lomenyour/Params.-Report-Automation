"""Сборка единственного листа «Данные» из книги ГТ и выгрузки датчиков.

Excel здесь является источником измерений и профиля поправок. Расчёты
выполняются над таблицей в памяти, поэтому позднее источник можно заменить БД.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json
import os
import re

import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI
from CoolProp.HumidAirProp import HAPropsSI
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import column_index_from_string, get_column_letter
from station_profiles import (
    StationRepository, get_station_repository, resolve_station,
    sensor_target_columns, unit_number,
)
SERVICE_FIELDS = {"date", "time", "milliseconds"}


@dataclass(frozen=True)
class SensorMapping:
    source: str
    target: str
    factor: float = 1.0
    parameter: str = ""
    source_unit: str = ""
    target_unit: str = ""
    status: str = "mapped"
    target_header: str = ""


@dataclass
class AssembledData:
    values: pd.DataFrame  # Внутренние имена колонок — Excel-буквы.
    headers: dict[str, str | None]
    imported_rows: int
    overlap_rows: int
    invalid_sensor_values: dict[str, int]
    verified_duplicate_columns: list[str]
    undated_rows: pd.DataFrame | None = None  # Сохраняются при экспорте, в расчёт не входят.
    source_diagnostics: dict | None = None

    def as_headered_frame(self) -> pd.DataFrame:
        result = self.values.reset_index(drop=True).copy()
        result.columns = [
            self.headers.get(column) or f"Unnamed: {index}"
            for index, column in enumerate(result.columns)
        ]
        return result


def list_source_sheets(path: str | Path) -> list[str]:
    if Path(path).suffix.casefold() == ".csv":
        return ["CSV"]
    with pd.ExcelFile(path, engine="calamine") as workbook:
        return list(workbook.sheet_names)


def _header_row(workbook: pd.ExcelFile, sheet_name: str) -> int:
    head = workbook.parse(sheet_name, header=None, nrows=60)
    for index, row in head.iterrows():
        labels = {str(value).strip().lower() for value in row if pd.notna(value)}
        if {"date", "time"} <= labels:
            return int(index)
    raise ValueError(f"На листе «{sheet_name}» не найдены колонки date и time.")


def source_columns(path: str | Path, sheet_name: str) -> list[str]:
    return list(_read_sensor_sheet(path, sheet_name).columns)


def template_columns(path: str | Path) -> dict[str, str | None]:
    with pd.ExcelFile(path, engine="calamine") as workbook:
        if not workbook.sheet_names or workbook.sheet_names[0] != "Данные":
            raise ValueError("Первый лист расчётной книги должен называться «Данные».")
        raw = workbook.parse("Данные", header=None, nrows=1)
        row = raw.iloc[0]
    headed = [index for index, value in enumerate(row) if pd.notna(value)]
    if not headed:
        raise ValueError("На листе «Данные» нет заголовков колонок.")
    return {
        get_column_letter(index + 1): None if pd.isna(value) else str(value)
        for index, value in enumerate(row)
    }


def _mapping_profile_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
    return base / "GTU_Report" / "sensor_mapping_profiles.json"


def _profile_key(book_path: str | Path) -> str:
    stem = Path(book_path).stem
    match = re.search(
        r"^(.*?)[\s_-]+(?:ГТ|GT)[-\s_]*(\d+)(?=$|[^0-9])",
        stem, re.I,
    )
    if not match:
        raise ValueError(
            "В имени книги не найдены станция и номер ГТ для профиля поправок."
        )
    station = re.sub(r"[\s_]+", " ", match.group(1).strip()).casefold()
    return f"{station}|{match.group(2)}"


def load_saved_mappings(
    book_path: str | Path, sheet_headers: list[str],
    *, station_id: str | None = None,
    unit: str | None = None,
    repository: StationRepository | None = None,
    target_headers: dict | None = None,
) -> list[SensorMapping] | None:
    station = resolve_station(book_path, station_id, repository)
    if station is None:
        return None
    path = _mapping_profile_path()
    from sensor_mapping_store import load_mapping, load_store
    from parameter_mapping import parameter_targets
    saved = load_store(path)
    entries = load_mapping(path, station.id, unit or unit_number(book_path) or "", sheet_headers, store=saved)
    if entries is None:
        legacy = saved.get("legacy", {})
        turbine = unit or unit_number(book_path)
        key = f"{station.id}|{turbine or ''}|{'|'.join(sheet_headers)}"
        entries = legacy.get(key)
        # Старые назначения переносим только при совпадении станции по имени.
        detected = resolve_station(book_path, repository=repository)
        if entries is None and detected is not None and detected.id == station.id and turbine == unit_number(book_path):
            entries = legacy.get(f"{_profile_key(book_path)}|{'|'.join(sheet_headers)}")
        if entries is None:
            return None
    try:
        known = {entry["source"].casefold(): SensorMapping(**entry) for entry in entries}
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("Повреждена запись маппинга; JSON оставлен без изменений.") from error
    targets = parameter_targets(target_headers or {}, station.id)
    result = []
    for header in sheet_headers:
        if header.casefold() in SERVICE_FIELDS:
            continue
        item = known.get(header.casefold(), SensorMapping(header, ""))
        item = replace(item, source=header)
        if target_headers and item.parameter and item.status != "deferred":
            item = replace(item, target=targets.get(item.parameter, ""))
        elif target_headers and item.target_header and target_headers.get(item.target) != item.target_header:
            item = replace(item, target="")
        result.append(item)
    return result


def save_mappings(
    book_path: str | Path, sheet_headers: list[str],
    mappings: list[SensorMapping],
    *, station_id: str | None = None,
    unit: str | None = None,
    repository: StationRepository | None = None,
    target_headers: dict | None = None,
) -> None:
    station = resolve_station(book_path, station_id, repository)
    if station is None:
        raise ValueError("Выберите ТЭЦ перед сохранением соответствий датчиков.")
    path = _mapping_profile_path()
    from sensor_mapping_store import save_mapping
    entries = [asdict(replace(item, target_header=(target_headers or {}).get(item.target, item.target_header) or "")) for item in mappings]
    save_mapping(path, station.id, unit or unit_number(book_path) or "", sheet_headers, entries)


def suggest_mappings(
    source_headers: list[str], book_path: str | Path,
    verified_duplicates: set[str] | None = None,
    *, station_id: str | None = None,
    unit: str | None = None,
    repository: StationRepository | None = None,
    target_headers: dict | None = None,
) -> list[SensorMapping]:
    """Предлагает только каналы выбранной ТЭЦ и ГТ; неизвестные — вручную."""
    repository = repository or get_station_repository()
    station = resolve_station(book_path, station_id, repository)
    gt_number = unit or unit_number(book_path)
    channels = repository.get_channels(station.id) if station else ()
    by_code = {channel.code.casefold(): channel for channel in channels
               if channel.unit_number == gt_number}
    from parameter_mapping import parameter_targets
    from source_variants import match_variant
    targets = parameter_targets(target_headers or {}, station.id if station else None)
    variant = match_variant(source_headers, station.company_id) if station and not by_code else None
    variant_codes = {entry["tag"].casefold(): entry for entry in variant["assignments"]} if variant else {}
    suggestions: list[SensorMapping] = []
    for header in source_headers:
        if header.lower() in SERVICE_FIELDS or header in (verified_duplicates or set()):
            continue
        channel = by_code.get(header.casefold())
        if channel:
            # Подтверждённые станционные назначения имеют приоритет над
            # неоднозначными названиями старой книги. Перестановка по похожему
            # заголовку меняла уже проверенную подстановку СызТЭЦ.
            suggestions.append(SensorMapping(header, channel.target_column, channel.factor,
                                             parameter=channel.parameter_id))
        elif header.casefold() in variant_codes:
            entry = variant_codes[header.casefold()]
            suggestions.append(SensorMapping(header, targets.get(entry["parameter"], ""), parameter=entry["parameter"], source_unit=entry.get("unit", "")))
        else:
            suggestions.append(SensorMapping(header, ""))
    return suggestions


def validate_mappings(
    mappings: list[SensorMapping], source_headers: list[str],
    verified_duplicates: set[str] | None = None,
    target_headers: dict[str, str | None] | None = None,
    *, allowed_targets: set[str] | None = None,
) -> None:
    allowed_targets = sensor_target_columns() if allowed_targets is None else allowed_targets
    available = set(source_headers)
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for mapping in mappings:
        if mapping.source not in available:
            raise ValueError(f"В выгрузке нет канала {mapping.source!r}.")
        if mapping.source in seen_sources:
            raise ValueError(f"Канал {mapping.source!r} назначен дважды.")
        if mapping.status == "deferred":
            seen_sources.add(mapping.source)
            continue
        if mapping.status != "mapped":
            raise ValueError(f"Неизвестный статус канала {mapping.source}.")
        if not mapping.target or not re.fullmatch(r"[A-Z]{1,3}", mapping.target):
            raise ValueError(f"Для канала {mapping.source!r} не выбрана колонка листа.")
        if mapping.target in {"A", "B", "AD"}:
            raise ValueError(f"Колонка {mapping.target} зарезервирована.")
        if target_headers is not None:
            from parameter_mapping import parameter_targets
            allowed_targets = allowed_targets | set(parameter_targets(target_headers).values())
        if target_headers is not None and mapping.target not in allowed_targets:
            last = max(column_index_from_string(col) for col in target_headers)
            if column_index_from_string(mapping.target) <= last:
                raise ValueError(
                    f"Колонка {mapping.target} относится к расчётной части книги. "
                    f"Для нового канала используйте колонку после {get_column_letter(last)}."
                )
        if mapping.target in seen_targets:
            raise ValueError(f"На колонку {mapping.target} назначено два канала.")
        if target_headers:
            from parameter_mapping import header_unit, unit_factor, unit_info
            book_unit = header_unit(target_headers.get(mapping.target))
            if unit_info(book_unit) and unit_info(mapping.target_unit):
                if unit_factor(book_unit, mapping.target_unit) != 1:
                    raise ValueError(f"Колонка {mapping.target} хранит {book_unit}. Единицы назначения должны соответствовать книге.")
        if mapping.source_unit and mapping.target_unit:
            from parameter_mapping import unit_factor
            expected_factor = unit_factor(mapping.source_unit, mapping.target_unit)
            if not np.isclose(mapping.factor, expected_factor, rtol=1e-9, atol=0):
                raise ValueError(f"Коэффициент {mapping.source} не соответствует выбранным единицам.")
        if not np.isfinite(mapping.factor) or mapping.factor == 0:
            raise ValueError(f"Неверный коэффициент для {mapping.source!r}.")
        seen_sources.add(mapping.source)
        seen_targets.add(mapping.target)
    missing = {
        header for header in source_headers
        if header.lower() not in SERVICE_FIELDS
        and header not in (verified_duplicates or set())
        and header not in seen_sources
    }
    if missing:
        raise ValueError(f"Не назначены каналы: {', '.join(sorted(missing))}.")


def _verified_duplicates(raw: pd.DataFrame, station_id: str,
                         repository: StationRepository | None = None) -> set[str]:
    """Разрешает пропуск только точно совпавших производных колонок."""
    repository = repository or get_station_repository()
    result = set()
    for relation in repository.get_duplicates(station_id):
        derived, original = relation.derived_code, relation.source_code
        if derived not in raw or original not in raw:
            continue
        left = pd.to_numeric(raw[derived], errors="coerce")
        right = pd.to_numeric(raw[original], errors="coerce") * relation.factor
        both = left.notna() & right.notna()
        if both.any() and (left.notna() == right.notna()).all() and np.allclose(
            left[both], right[both], rtol=0, atol=1e-8
        ):
            result.add(derived)
    return result


def _read_sensor_sheet(path: str | Path, sheet_name: str) -> pd.DataFrame:
    from source_readers import read_sensor_sheet
    return read_sensor_sheet(path, sheet_name)


def source_channel_info(path, sheet_name):
    return _read_sensor_sheet(path, sheet_name).attrs.get("channel_info", {})


def source_selection_info(path, sheet_name):
    frame = _read_sensor_sheet(path, sheet_name)
    return {"format": frame.attrs.get("source_format", ""), "rows": len(frame),
            "skipped_rows": frame.attrs.get("skipped_rows", 0), "invalid_dates": frame.attrs.get("invalid_dates", 0)}


def source_mapping_info(
    path: str | Path, sheet_name: str,
    *, station_id: str,
    repository: StationRepository | None = None,
) -> tuple[list[str], set[str]]:
    """Каналы листа и производные колонки, проверенные по числам."""
    raw = _read_sensor_sheet(path, sheet_name)
    return list(raw.columns), _verified_duplicates(raw, station_id, repository)


def _read_template(path: str | Path) -> tuple[pd.DataFrame, dict[str, str | None], pd.DataFrame]:
    with pd.ExcelFile(path, engine="calamine") as workbook:
        if not workbook.sheet_names or workbook.sheet_names[0] != "Данные":
            raise ValueError("Первый лист расчётной книги должен называться «Данные».")
        raw = workbook.parse("Данные", header=None)
    headed = [index for index, value in enumerate(raw.iloc[0]) if pd.notna(value)]
    if not headed:
        raise ValueError("На листе «Данные» нет заголовков колонок.")
    headers = {
        get_column_letter(index + 1): None if pd.isna(value) else str(value)
        for index, value in enumerate(raw.iloc[0])
    }
    data = raw.iloc[1:].copy().astype(object)
    data.columns = list(headers)
    dates = pd.to_datetime(data["B"], errors="coerce")
    undated_rows = data.loc[dates.isna()].copy()
    rounded = dates.dt.round("min")
    excessive_shift = dates.notna() & (
        (dates - rounded).abs() > pd.Timedelta(seconds=1)
    )
    if excessive_shift.any():
        raise ValueError(
            "В расчётной книге найдены даты со смещением больше секунды "
            "от целой минуты; автоматическое совмещение небезопасно."
        )
    dates = rounded
    data = data.loc[dates.notna()].copy()
    data.index = pd.DatetimeIndex(dates.loc[dates.notna()], name="timestamp")
    if data.index.has_duplicates:
        raise ValueError("В расчётной книге повторяются даты на листе «Данные».")
    data["B"] = data.index
    return data.sort_index(), headers, undated_rows


def _convert_sensor(series: pd.Series, factor: float) -> tuple[pd.Series, int]:
    decimal = series.map(lambda value: value.strip().replace(" ", "").replace(",", ".") if isinstance(value, str) else value)
    values = pd.to_numeric(decimal, errors="coerce")
    invalid = int((series.notna() & values.isna()).sum())
    converted = pd.Series(values * factor, index=series.index, dtype=object)
    converted.loc[series.notna() & values.isna()] = series.loc[
        series.notna() & values.isna()
    ]
    return converted, invalid


def assemble_sensor_data(
    book_path: str | Path,
    source_path: str | Path,
    source_sheet: str,
    mappings: list[SensorMapping],
    *, station_id: str | None = None,
    unit: str | None = None,
    repository: StationRepository | None = None,
) -> AssembledData:
    repository = repository or get_station_repository()
    station = resolve_station(book_path, station_id, repository)
    if station is None:
        raise ValueError("Выберите ТЭЦ перед обновлением данных датчиков.")
    template, headers, undated_rows = _read_template(book_path)
    raw = _read_sensor_sheet(source_path, source_sheet)
    duplicates = _verified_duplicates(raw, station.id, repository)
    validate_mappings(mappings, list(raw.columns), duplicates, headers,
                      allowed_targets=sensor_target_columns(station.id, repository))
    gt_number = unit or unit_number(book_path)
    if gt_number:
        channels = repository.get_channels(station.id)
        codes = {str(col).casefold() for col in raw.columns}
        expected_count = sum(channel.code.casefold() in codes for channel in channels
                             if channel.unit_number == gt_number)
        other_count = sum(channel.code.casefold() in codes for channel in channels
                          if channel.unit_number != gt_number)
        if other_count > expected_count:
            raise ValueError(
                f"Книга выбрана для ГТ-{gt_number}, но каналы листа "
                f"«{source_sheet}» относятся к другому агрегату."
            )

    all_dates = template.index.union(raw.index).sort_values()
    result = template.reindex(all_dates).copy()
    # В старой книге давление могло лежать в AD вместо AC. Заполняем
    # только пропуск AC, сохраняя обе исходные колонки без перезаписи.
    if "AD" in result and "AC" in result and not headers.get("AD"):
        shifted = template["AC"].isna() & template["AD"].notna()
        result.loc[template.index[shifted], "AC"] = template.loc[
            shifted, "AD"
        ].to_numpy()
    invalid_values: dict[str, int] = {}
    for mapping in mappings:
        if mapping.status == "deferred":
            existing = next((column for column, label in headers.items() if label == f"До уточнения: {mapping.source}"), None)
            column = existing or get_column_letter(max(column_index_from_string(key) for key in result.columns) + 1)
            result[column] = result[column].astype(object) if column in result else pd.Series(index=result.index, dtype=object)
            result.loc[raw.index, column] = raw[mapping.source].to_numpy()
            headers[column] = f"До уточнения: {mapping.source}"
            continue
        converted, invalid = _convert_sensor(raw[mapping.source], mapping.factor)
        if mapping.target not in result:
            result[mapping.target] = pd.Series(index=result.index, dtype=object)
            headers[mapping.target] = mapping.source
        result.loc[raw.index, mapping.target] = converted.to_numpy()
        if invalid:
            invalid_values[mapping.source] = invalid

    result["B"] = result.index
    result["A"] = np.arange(len(result), dtype=float) * 0.5
    return AssembledData(
        values=result,
        headers=headers,
        imported_rows=len(raw),
        overlap_rows=len(template.index.intersection(raw.index)),
        invalid_sensor_values=invalid_values,
        verified_duplicate_columns=sorted(duplicates),
        undated_rows=undated_rows,
        source_diagnostics=source_selection_info(source_path, source_sheet),
    )


def read_calculation_profile(book_path: str | Path, *, gas_passport=None,
                             correction_profile=None, station_id=None, unit=None, repository=None):
    """Рабочий профиль: только именованный JSON/встроенный набор и паспорт газа."""
    from correction_profiles import require_profile
    from gas_passport import resolve_passport
    from station_profiles import unit_number
    station = resolve_station(book_path, station_id, repository)
    if station is None:
        raise ValueError("Выберите ТЭЦ для профиля поправок.")
    turbine = unit or unit_number(book_path)
    corrections = correction_profile or require_profile(book_path, station.id, turbine)
    if corrections.station_id != station.id or corrections.unit != turbine:
        raise ValueError("Выбран профиль поправок другой ТЭЦ или ГТ.")
    passport = gas_passport or resolve_passport(book_path, station.id, turbine)
    if passport is None:
        raise ValueError("Заполните паспорт газа для выбранных ТЭЦ и ГТ.")
    if passport.station_id != station.id or passport.unit != turbine:
        raise ValueError("Паспорт газа относится к другой ТЭЦ или ГТУ.")
    from gas_passport import passport_entries
    first = passport_entries(passport)[0]
    return {**corrections.values, "gas_c_h": first.carbon_hydrogen_ratio,
            "gas_density": first.density_kg_per_nm3,
            "qnr_denominator": first.density_kg_per_nm3,
            "gas_q_lower": first.q_lower_mj_per_nm3, "gas_history": passport.to_dict()}


def _number(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame:
        return np.full(len(frame), np.nan, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def _polynomial(profile: dict[str, float], prefix: str, terms: tuple[str, ...],
                x: np.ndarray) -> np.ndarray:
    return np.polyval([profile[f"{prefix}.{term}"] for term in terms], x)


def _coolprop_columns(frame: pd.DataFrame) -> None:
    """Влажность, плотность и термодинамика по формулам книги."""
    c, f, g = (_number(frame, col) for col in ("C", "F", "G"))
    n, p, w, x = (_number(frame, col) for col in ("N", "P", "W", "X"))
    count = len(frame)
    result = {col: np.full(count, np.nan, dtype=float) for col in (
        "I", "Q", "R", "Z", "AA", "AB"
    )}
    reference_h = PropsSI("H", "T", 273.15, "P", 101325, "HEOS::Air")
    for i in range(count):
        if np.isfinite(c[i]) and c[i] > 0 and np.isfinite(f[i]) and np.isfinite(g[i]):
            try:
                result["I"][i] = HAPropsSI(
                    "W", "T", f[i] + 273.15, "P", c[i],
                    "R", max(g[i], 0.0) / 100.0,
                )
            except (ValueError, OverflowError):
                pass
        if np.isfinite(n[i]) and n[i] > 0 and np.isfinite(p[i]):
            if np.isfinite(result["I"][i]):
                try:
                    result["Q"][i] = 100.0 * HAPropsSI(
                        "R", "T", p[i] + 273.15, "P", n[i],
                        "W", result["I"][i],
                    )
                    result["R"][i] = 1.0 / HAPropsSI(
                        "Vha", "T", p[i] + 273.15, "P", n[i],
                        "R", result["Q"][i] / 100.0,
                    )
                except (ValueError, OverflowError, ZeroDivisionError):
                    pass
            try:
                h1 = PropsSI("H", "T", p[i] + 273.15, "P", n[i], "HEOS::Air")
                result["Z"][i] = (h1 - reference_h) / 1000.0
                if np.isfinite(x[i]) and x[i] > 0 and np.isfinite(w[i]):
                    outlet_p = x[i] * 1_000_000.0
                    h2 = PropsSI(
                        "H", "T", w[i] + 273.15, "P", outlet_p, "HEOS::Air"
                    )
                    result["AA"][i] = (h2 - reference_h) / 1000.0
                    if outlet_p > n[i] and abs(h2 - h1) > 1e-10:
                        s1 = PropsSI(
                            "S", "T", p[i] + 273.15, "P", n[i], "HEOS::Air"
                        )
                        h2s = PropsSI("H", "S", s1, "P", outlet_p, "HEOS::Air")
                        result["AB"][i] = (h2s - h1) / (h2 - h1) * 100.0
            except (ValueError, OverflowError):
                pass
    for column, values in result.items():
        frame[column] = values


def calculate_data_columns(data: AssembledData,
                           profile: dict[str, float], *, thermodynamics=True) -> AssembledData:
    """Пересчитывает производные колонки без ссылок на другие листы."""
    if data.headers:
        from parameter_mapping import parameter_targets
        actual = parameter_targets(data.headers, "syz_tec")
        expected = {"atmospheric_pressure":"C", "ambient_temperature":"F", "relative_humidity":"G",
                    "inlet_temperature":"P", "outlet_temperature":"W", "outlet_pressure":"X",
                    "vna":"V", "rpm":"AM", "power":"AO", "fuel_flow":"AS"}
        mismatched = [f"{key}: {actual[key]} вместо {column}" for key,column in expected.items()
                      if key in actual and actual[key] != column]
        if mismatched:
            raise ValueError("Структура книги не соответствует методике СызТЭЦ: " + "; ".join(mismatched) + ". Чужая методика не применяется.")
    frame = data.values
    q = lambda cell: profile[cell]
    c, f, g, l, m, p, x = (
        _number(frame, col) for col in ("C", "F", "G", "L", "M", "P", "X")
    )
    frame["D"] = q("pressure_power.p1") * c / 1000.0 + q("pressure_power.p0")
    frame["H"] = (
        (q("humidity_power.h3") * p**3 + q("humidity_power.h2") * p**2 + q("humidity_power.h0")) * g
        + q("humidity_power.b3") * p**3 + q("humidity_power.b2") * p**2 + q("humidity_power.b0")
    )
    frame["N"] = c - m
    frame["O"] = (
        _polynomial(profile, "inlet_loss", ("a2", "a1", "a0"), p) * l
        + _polynomial(profile, "inlet_loss", ("b2", "b1", "b0"), p)
    )
    frame["S"] = p - f
    frame["T"] = _polynomial(profile, "temperature_power", ("t3", "t2", "t1", "t0"), p)
    frame["U"] = _polynomial(profile, "temperature_efficiency", ("t4", "t3", "t2", "t1", "t0"), p)
    with np.errstate(divide="ignore", invalid="ignore"):
        frame["Y"] = x * 1_000_000.0 / _number(frame, "N")
    frame["AE"] = (
        _polynomial(profile, "outlet_loss", ("a2", "a1", "a0"), p)
        * _number(frame, "AC")
        + _polynomial(profile, "outlet_loss", ("b2", "b1", "b0"), p)
    )
    frame["AI"] = q("fuel_temperature.t1") * _number(frame, "AH") + q("fuel_temperature.t0")
    rpm = _number(frame, "AM") / 5200.0
    frame["AN"] = (
        _polynomial(profile, "speed_power", tuple(f"n3_t{i}" for i in range(5,-1,-1)), p) * rpm**3
        + _polynomial(profile, "speed_power", tuple(f"n2_t{i}" for i in range(5,-1,-1)), p) * rpm**2
        + _polynomial(profile, "speed_power", tuple(f"n1_t{i}" for i in range(5,-1,-1)), p) * rpm
        + _polynomial(profile, "speed_power", tuple(f"n0_t{i}" for i in range(5,-1,-1)), p)
    )
    if thermodynamics:
        _coolprop_columns(frame)
    recalculate_gas_columns(frame, profile)
    return data


def recalculate_gas_columns(frame: pd.DataFrame, profile: dict[str, float]) -> None:
    """Меняет только газозависимую часть, остальные поправки остаются прежними."""
    q = lambda cell: profile[cell]
    density = profile["gas_density"]
    if "gas_history" in profile:
        from gas_passport import GasPassport, gas_values
        gas = gas_values(GasPassport.from_dict(profile["gas_history"]), frame["B"])
        density = gas["density_kg_per_nm3"]
        frame["AJ"] = gas["carbon_hydrogen_ratio"]
        frame["AK"] = gas["q_lower_mj_per_nm3"] / density
    else:
        frame["AJ"] = profile["gas_c_h"]
        frame["AK"] = profile["gas_q_lower"] / profile["qnr_denominator"]
    aj, ak = (_number(frame, col) for col in ("AJ", "AK"))
    frame["AL"] = (
        _polynomial(profile, "fuel_properties", ("q2", "q1", "q0"), aj) * ak
        + _polynomial(profile, "fuel_properties", ("b2", "b1", "b0"), aj)
    )
    denominator = np.ones(len(frame), dtype=float)
    for column in ("D", "H", "O", "T", "AE", "AI", "AL", "AN"):
        denominator *= _number(frame, column)
    with np.errstate(divide="ignore", invalid="ignore"):
        power = _number(frame, "AO") / denominator
    power[~np.isfinite(power)] = np.nan
    frame["AQ"] = power
    frame["AT"] = _number(frame, "AS") * 3600.0 / density
    frame["AV"] = (power * q("fuel_reference.n1") + q("fuel_reference.n0")) * 3600.0 / density
    with np.errstate(divide="ignore", invalid="ignore"):
        specific = _number(frame, "AV") / power
    specific[~np.isfinite(specific)] = np.nan
    frame["AX"] = specific
    for output, source in (("AP", "AO"), ("AR", "AQ"),
                           ("AU", "AT"), ("AW", "AV")):
        values = _number(frame, source)
        averaged = np.full(len(frame), np.nan)
        for i in range(1, len(frame), 2):
            pair = values[i - 1:i + 1]
            if np.isfinite(pair).any():
                averaged[i] = float(np.nanmean(pair))
        frame[output] = averaged


def apply_economic_columns(data: AssembledData, economics_result: dict) -> None:
    """Записывает построчные потери действующей методики в колонки книги."""
    frame = data.values
    loss_columns = [
        column for column, header in data.headers.items()
        if header and header.strip().lower() in {"перерасход", "недовыработка"}
    ]
    for column in loss_columns:
        frame[column] = np.nan
        next_column = get_column_letter(column_index_from_string(column) + 1)
        if data.headers.get(next_column) in (None, ""):
            frame[next_column] = np.nan
            data.headers.setdefault(next_column, None)
    records = economics_result.get("row_losses")
    if records is None or records.empty:
        return
    losses = records.copy()
    losses["date"] = pd.to_datetime(losses["date"]).dt.round("min")
    if losses["date"].duplicated().any():
        raise ValueError("Экономический расчёт вернул повторяющиеся даты.")
    losses = losses.set_index("date").sort_index()
    source_for_header = {
        "перерасход": "fuel_loss_rate",
        "недовыработка": "power_loss_rate",
    }
    for column, header in list(data.headers.items()):
        if header is None:
            continue
        source = source_for_header.get(header.strip().lower())
        if source is None:
            continue
        rates = losses[source].reindex(frame.index).fillna(0.0)
        frame[column] = rates.to_numpy(dtype=float)
        next_column = get_column_letter(column_index_from_string(column) + 1)
        if data.headers.get(next_column) not in (None, ""):
            continue
        averaged = pd.Series(np.nan, index=frame.index, dtype=float)
        for _, group in losses.groupby("period", sort=False):
            dates = group.index.sort_values()
            for index in range(0, len(dates) - 1, 2):
                pair = rates.reindex(dates[index:index + 2]).to_numpy(dtype=float)
                averaged.loc[dates[index + 1]] = float(pair.mean())
        frame[next_column] = averaged.to_numpy()
        data.headers.setdefault(next_column, None)


def save_data_sheet(data: AssembledData, output_path: str | Path) -> Path:
    """Сохраняет только «Данные» как значения, без внешних ссылок и макросов."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Данные")
    sheet.freeze_panes = "B2"
    last_column = max(column_index_from_string(col) for col in data.values.columns)
    letters = [get_column_letter(index) for index in range(1, last_column + 1)]
    sheet.append([data.headers.get(col) for col in letters])
    from itertools import chain
    rows = chain(
        data.values.reindex(columns=letters).itertuples(index=False, name=None),
        data.undated_rows.reindex(columns=letters).itertuples(index=False, name=None)
        if data.undated_rows is not None else (),
    )
    for row in rows:
        output = []
        for value in row:
            if pd.isna(value):
                output.append(None)
            elif isinstance(value, pd.Timestamp):
                output.append(value.to_pydatetime())
            elif isinstance(value, np.generic):
                output.append(value.item())
            elif isinstance(value, str) and value.startswith("="):
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"
                output.append(cell)
            else:
                output.append(value)
        sheet.append(output)
    book.save(path)
    return path
