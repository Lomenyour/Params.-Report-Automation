"""Паспорт газа: явные единицы, принадлежность ГТ и атомарное сохранение."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd
from gas_composition import CH_METHOD, calculate_ch

COMPONENTS = ("Methane", "Ethane", "n-Propane", "IsoButane", "n-Butane",
              "n-Pentane", "Isopentane", "n-Hexane", "n-Heptane",
              "CarbonDioxide", "Nitrogen", "Oxygen", "Helium", "Hydrogen")
MARKER = "GTU_GAS_PASSPORT_V1"


def number(value, label):
    try:
        result = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}: введите число.") from error
    if not math.isfinite(result):
        raise ValueError(f"{label}: требуется конечное число.")
    return result


@dataclass(frozen=True)
class GasPassport:
    station_id: str
    unit: str
    density_kg_per_nm3: float
    q_lower_mj_per_nm3: float
    carbon_hydrogen_ratio: float
    components: tuple[tuple[str, float], ...] = ()
    updated_at: str = ""
    valid_from: str = ""
    valid_until: str = ""
    carbon_hydrogen_ratio_method: str = ''

    @property
    def q_lower_mj_per_kg(self):
        return self.q_lower_mj_per_nm3 / self.density_kg_per_nm3

    @property
    def composition_warning(self):
        total = sum(value for _, value in self.components)
        if self.components and not math.isclose(total, 1., abs_tol=.001):
            return (f"Сумма долей состава = {total:.6g}, ожидается 1. "
                    "Значения сохранены без нормализации; проверьте паспорт.")
        return ""

    def to_dict(self):
        return {**asdict(self), "components": dict(self.components)}

    @classmethod
    def from_dict(cls, data, station_id=None, unit=None):
        if "entries" in data:
            return GasPassportHistory.from_dict(data, station_id, unit)
        station, turbine = str(data.get("station_id", "")), str(data.get("unit", ""))
        from station_profiles import valid_unit_number
        if not station or not valid_unit_number(turbine):
            raise ValueError("В паспорте газа не указаны ТЭЦ и номер ГТ.")
        if station_id is not None and station != station_id or unit is not None and turbine != str(unit):
            raise ValueError("Паспорт газа относится к другой ТЭЦ или ГТ.")
        fields = ("density_kg_per_nm3", "q_lower_mj_per_nm3")
        values = [number(data.get(key), key) for key in fields]
        if any(value <= 0 for value in values):
            raise ValueError("Плотность и Qнр должны быть больше нуля.")
        components, seen = [], set()
        source = data.get("components", {})
        rows = source.items() if isinstance(source, dict) else source
        for name, raw in rows:
            name = str(name).strip()
            if not name or name.casefold() in seen:
                raise ValueError("В составе газа есть пустой или повторный компонент.")
            seen.add(name.casefold())
            value = number(raw, name)
            if not 0 <= value <= 1:
                raise ValueError(f"Доля {name} должна быть от 0 до 1.")
            components.append((name, value))
        method=str(data.get('carbon_hydrogen_ratio_method') or '')
        if method not in ('',CH_METHOD):
            raise ValueError('Неизвестный способ расчёта C/H.')
        if method==CH_METHOD or data.get('carbon_hydrogen_ratio') is None:
            ratio=calculate_ch(components)
            if method==CH_METHOD and data.get('carbon_hydrogen_ratio') is not None:
                stored=number(data['carbon_hydrogen_ratio'],'C/H')
                if not math.isclose(stored,ratio,rel_tol=1e-10,abs_tol=1e-12):
                    raise ValueError('Сохранённое автоматическое C/H не совпадает с составом газа.')
            method=CH_METHOD
        else:
            ratio=number(data['carbon_hydrogen_ratio'],'C/H')
            if ratio<=0:raise ValueError('C/H прежнего паспорта должно быть больше нуля.')
        start, end = (str(data.get(key) or "").strip() for key in ("valid_from", "valid_until"))
        if bool(start) != bool(end):
            raise ValueError("Укажите обе границы действия паспорта либо оставьте обе пустыми для всего диапазона.")
        if start:
            start, end = _gas_date(start), _gas_date(end)
            if start >= end:
                raise ValueError("Начало действия паспорта должно быть раньше окончания.")
            start, end = start.isoformat(), end.isoformat()
        return cls(station, turbine, *values, ratio, tuple(components), str(data.get("updated_at", "")), start, end, method)


def _gas_date(value):
    try:
        result = pd.to_datetime(value, format="ISO8601") if isinstance(value, str) else pd.Timestamp(value)
        if pd.isna(result) or result.tzinfo is not None:
            raise ValueError()
        return result
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"Неверная дата паспорта газа: {value}. Используйте ГГГГ-ММ-ДД ЧЧ:ММ в местном времени измерений.") from error


def passport_entries(passport):
    return passport.entries if isinstance(passport, GasPassportHistory) else (passport,)


@dataclass(frozen=True)
class GasPassportHistory:
    station_id: str
    unit: str
    entries: tuple[GasPassport, ...]
    updated_at: str = ""

    def to_dict(self):
        return {"station_id": self.station_id, "unit": self.unit,
                "entries": [entry.to_dict() for entry in self.entries], "updated_at": self.updated_at}

    @property
    def composition_warning(self):
        return "\n".join(f"Паспорт {i}: {entry.composition_warning}" for i, entry in enumerate(self.entries, 1) if entry.composition_warning)

    @classmethod
    def from_dict(cls, data, station_id=None, unit=None):
        station, turbine = str(data.get("station_id", "")), str(data.get("unit", ""))
        if station_id is not None and station != station_id or unit is not None and turbine != str(unit):
            raise ValueError("История паспортов относится к другой ТЭЦ или ГТ.")
        raw_entries = data.get("entries", [])
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("Добавьте хотя бы один паспорт газа.")
        entries = tuple(GasPassport.from_dict(entry, station, turbine) for entry in raw_entries)
        if any(not isinstance(entry, GasPassport) for entry in entries):
            raise ValueError("Вложенные истории паспортов недопустимы.")
        if len(entries) > 1 and any(not entry.valid_from for entry in entries):
            raise ValueError("Для нескольких паспортов укажите срок действия каждого.")
        entries = tuple(sorted(entries, key=lambda entry: entry.valid_from))
        for previous, current in zip(entries, entries[1:]):
            if _gas_date(previous.valid_until) > _gas_date(current.valid_from):
                raise ValueError("Сроки действия паспортов газа пересекаются.")
        return cls(station, turbine, entries, str(data.get("updated_at", "")))


def gas_values(passport, dates):
    """Select one passport per dated measurement; undated rows remain unavailable."""
    import numpy as np
    dates = pd.Series(pd.to_datetime(dates, errors="coerce")).reset_index(drop=True)
    if getattr(dates.dt, "tz", None) is not None:
        raise ValueError("Часовой пояс паспортов и измерений должен быть согласован явно.")
    result = {key: np.full(len(dates), np.nan) for key in
              ("density_kg_per_nm3", "q_lower_mj_per_nm3", "carbon_hydrogen_ratio")}
    covered = np.zeros(len(dates), dtype=bool)
    for entry in passport_entries(passport):
        mask = dates.notna()
        if entry.valid_from:
            mask &= (dates >= _gas_date(entry.valid_from)) & (dates < _gas_date(entry.valid_until))
        mask = mask.to_numpy()
        if (covered & mask).any():
            raise ValueError("Для одной даты выбрано несколько паспортов газа.")
        covered |= mask
        for key in result:
            result[key][mask] = getattr(entry, key)
    missing = dates.notna().to_numpy() & ~covered
    if missing.any():
        examples = dates.loc[missing].head(3).dt.strftime("%d.%m.%Y %H:%M").tolist()
        raise ValueError(f"Нет паспорта газа для {int(missing.sum())} строк: {', '.join(examples)}. Дополните сроки действия.")
    return result


def passport_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
    return base / "GTU_Report" / "gas_passport_history.json"


def _read_store():
    path = passport_path()
    if not path.exists():
        legacy = path.with_name("gas_passports.json")
        if legacy.exists():
            path = legacy
        else:
            return {"schema_version": 1, "passports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] not in (1, 2) or not isinstance(data["passports"], dict):
            raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Не удалось прочитать справочник паспортов газа: {path}") from error


def load_passport(station_id, unit):
    data = _read_store()["passports"].get(f"{station_id}|{unit}")
    return None if data is None else GasPassport.from_dict(data, station_id, unit)


def save_passport(passport):
    passport = GasPassport.from_dict({**passport.to_dict(),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    from json_store import transaction, write_json
    with transaction():
        data = _read_store()
        data["schema_version"] = 2
        data["passports"][f"{passport.station_id}|{passport.unit}"] = passport.to_dict()
        write_json(passport_path(), data)
    return passport


def embedded_passport(frame, station_id, unit):
    matches = [i for i, value in enumerate(frame.iloc[:, 0]) if value == MARKER]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("На листе «Поправки» несколько паспортов газа.")
    start = matches[0]
    try:
        data = json.loads(frame.iat[start, 1])
    except (ValueError, TypeError) as error:
        raise ValueError("Повреждён встроенный паспорт газа.") from error
    return GasPassport.from_dict(data, station_id, unit)


def read_book_passport(path, station_id, unit):
    """Новый именованный блок либо исходный паспорт в верхней части «Результаты»."""
    if not unit:
        return None
    with pd.ExcelFile(path, engine="calamine") as book:
        if "Поправки" in book.sheet_names:
            passport = embedded_passport(book.parse("Поправки", header=None), station_id, unit)
            if passport is not None:
                return passport
        if "Результаты" not in book.sheet_names:
            return None
        frame = book.parse("Результаты", header=None, nrows=4)
    composition, candidates = {}, []
    labels = {"ρ,кг/м3": "density_kg_per_nm3", "ρ,кг/м³": "density_kg_per_nm3",
              "qнр,мдж/м3": "q_lower_mj_per_nm3", "qнр,мдж/м³": "q_lower_mj_per_nm3",
              "c/h": "carbon_hydrogen_ratio"}
    for row in range(len(frame)):
        matches = {key: [] for key in set(labels.values())}
        for col in range(len(frame.columns)):
            text = str(frame.iat[row, col]).strip()
            label = labels.get(text.lower().replace(" ", "").replace("\n", ""))
            if label and row + 1 < len(frame):
                matches[label].append(col)
            if text in COMPONENTS:
                adjacent = frame.iat[row - 1, col] if row else frame.iat[row + 1, col]
                composition[text] = adjacent
        if all(matches.values()):
            from itertools import product
            keys = list(matches)
            for positions in product(*(matches[key] for key in keys)):
                candidates.append((max(positions) - min(positions), row,
                                   {key: frame.iat[row + 1, col] for key, col in zip(keys, positions)}))
    if not candidates:
        return None
    span = min(candidate[0] for candidate in candidates)
    nearest = [candidate for candidate in candidates if candidate[0] == span]
    if len(nearest) != 1:
        raise ValueError("В книге несколько равнозначных блоков плотность — Qнр — C/H. Заполните паспорт газа вручную.")
    found = nearest[0][2]
    return GasPassport.from_dict({"station_id": station_id, "unit": str(unit),
                                  **found, "components": composition})


def resolve_passport(path, station_id, unit):
    """Явно сохранённый пользователем паспорт имеет приоритет над старой книгой."""
    if not unit:
        return None
    return load_passport(station_id, unit) or read_book_passport(path, station_id, unit)


def write_passport(sheet, passport):
    if isinstance(passport, GasPassportHistory):
        sheet.append([MARKER, json.dumps(passport.to_dict(), ensure_ascii=False)])
        sheet.append(["История паспортов газа, использованная в расчёте"])
        sheet.append(["ТЭЦ", passport.station_id, "ГТ", passport.unit])
        sheet.append(["Действует с", "До (не включая)", "Плотность, кг/нм³", "Qнр, МДж/нм³", "C/H, кг C/кг H"])
        for entry in passport.entries:
            sheet.append([entry.valid_from or "Весь диапазон", entry.valid_until,
                          entry.density_kg_per_nm3, entry.q_lower_mj_per_nm3, entry.carbon_hydrogen_ratio])
            for component, value in entry.components:
                sheet.append([component, value])
        return
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    rows = [
        [MARKER, json.dumps(passport.to_dict(), ensure_ascii=False)],
        ["Паспорт газа, использованный в расчёте"],
        ["ТЭЦ (идентификатор)", passport.station_id], ["ГТ", passport.unit],
        ["Параметр", "Значение", "Единицы"],
        ["Плотность", passport.density_kg_per_nm3, "кг/нм³"],
        ["Qнр (паспорт)", passport.q_lower_mj_per_nm3, "МДж/нм³"],
        ["Qнр для массовой поправки", passport.q_lower_mj_per_kg, "МДж/кг"],
        ["C/H", passport.carbon_hydrogen_ratio, "кг C/кг H"],
        ["Компонент", "Молярная доля", "0..1"],
        *[[name, value] for name, value in passport.components],
    ]
    for i, values in enumerate(rows):
        cells = []
        for value in values:
            cell = WriteOnlyCell(sheet, value)
            cell.font = Font(name="Calibri", size=11, bold=i in (1, 4, 9))
            if i in (1, 4, 9):
                cell.fill = PatternFill("solid", fgColor="DFEAF4")
            if isinstance(value, float):
                cell.number_format = "0.000000"
            cells.append(cell)
        sheet.append(cells)
