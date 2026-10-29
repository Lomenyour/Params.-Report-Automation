"""Именованные коэффициенты методики СызТЭЦ, справочник по ТЭЦ/ГТ.

source_cell — только подсказка и однократная миграция проверенных старых
шаблонов. Ни разрешение рабочего профиля, ни математический расчёт адресов
коэффициентов Excel не используют.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import pandas as pd
from gas_passport import number

METHOD = "syz_tec_v1"
MARKER = "GTU_CORRECTIONS_V1"


@dataclass(frozen=True)
class Coefficient:
    key: str
    label: str
    source_cell: str


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    formula: str
    fields: tuple[Coefficient, ...]


def _fields(prefix, names, cells):
    return tuple(Coefficient(f"{prefix}.{name}", name, cell) for name, cell in zip(names, cells))


GROUPS = (
    Group("pressure_power", "Атмосферное давление → мощность", "kPN = p1 × Pатм/1000 + p0; Pатм в Па",
          _fields("pressure_power", ("p1", "p0"), ("M669", "N669"))),
    Group("humidity_power", "Влажность → мощность", "kφN = (h3×T³+h2×T²+h0)×φ + b3×T³+b2×T²+b0; φ в %",
          _fields("humidity_power", ("h3", "h2", "h0", "b3", "b2", "b0"),
                  ("T787", "V787", "X787", "AB788", "AD788", "AF788"))),
    Group("inlet_loss", "Потери давления на входе → мощность", "kΔPвхN = (a2×T²+a1×T+a0)×Δp + b2×T²+b1×T+b0; Δp в Па",
          _fields("inlet_loss", ("a2", "a1", "a0", "b2", "b1", "b0"),
                  ("V888", "W888", "X888", "AB888", "AC888", "AD888"))),
    Group("temperature_power", "Температура → мощность", "kTN = t3×T³+t2×T²+t1×T+t0",
          _fields("temperature_power", ("t3", "t2", "t1", "t0"), ("M712", "N712", "O712", "P712"))),
    Group("temperature_efficiency", "Температура → КПД", "kTη = t4×T⁴+t3×T³+t2×T²+t1×T+t0",
          _fields("temperature_efficiency", ("t4", "t3", "t2", "t1", "t0"), ("P507", "Q507", "R507", "S507", "T507"))),
    Group("outlet_loss", "Давление уходящих газов → мощность", "kΔPвыхN = (a2×T²+a1×T+a0)×Pвых + b2×T²+b1×T+b0; Pвых в кПа",
          _fields("outlet_loss", ("a2", "a1", "a0", "b2", "b1", "b0"),
                  ("T969", "U969", "V969", "AC969", "AD969", "AE969"))),
    Group("fuel_temperature", "Температура топлива → мощность", "ktгN = t1×tгаза+t0",
          _fields("fuel_temperature", ("t1", "t0"), ("T1107", "U1107"))),
    Group("fuel_properties", "C/H и Qнр → мощность", "k(c/h)N = (q2×CH²+q1×CH+q0)×Qнр + b2×CH²+b1×CH+b0; Qнр в МДж/кг",
          _fields("fuel_properties", ("q2", "q1", "q0", "b2", "b1", "b0"),
                  ("L1019", "M1019", "N1019", "R1019", "S1019", "T1019"))),
    Group("speed_power", "Обороты и температура → мощность", "knN = P3(T)×r³+P2(T)×r²+P1(T)×r+P0(T); r=n/5200; Pi — полиномы T пятой степени",
          tuple(Coefficient(f"speed_power.n{n}_t{t}", f"при r^{n} × T^{t}", f"{cell}851")
                for n, cells in ((3, ("U","V","W","X","Y","Z")),
                                 (2, ("AC","AD","AE","AF","AG","AH")),
                                 (1, ("AK","AL","AM","AN","AO","AP")),
                                 (0, ("AS","AT","AU","AV","AW","AX")))
                for t, cell in zip(range(5,-1,-1), cells))),
    Group("fuel_reference", "Расходная характеристика", "Bприв = (n1×Nприв+n0)×3600/ρ; Nприв в МВт, ρ в кг/нм³",
          _fields("fuel_reference", ("n1", "n0"), ("M605", "O605"))),
)
FIELDS = tuple(field for group in GROUPS for field in group.fields)
KEYS = frozenset(field.key for field in FIELDS)
LEGACY_CELLS = {field.source_cell: field.key for field in FIELDS}


def named_legacy_values(values):
    """Однократный перевод уже прочитанных значений старого шаблона."""
    return {**{key: values[cell] for cell, key in LEGACY_CELLS.items()},
            **{key: value for key, value in values.items() if key not in LEGACY_CELLS}}


@dataclass(frozen=True)
class CorrectionProfile:
    station_id: str
    unit: str
    coefficients: tuple[tuple[str, float], ...]
    method: str = METHOD
    revision: int = 0
    updated_at: str = ""
    source: str = ""

    @property
    def values(self):
        return dict(self.coefficients)

    def to_dict(self):
        return {"station_id": self.station_id, "unit": self.unit, "method": self.method,
                "revision": self.revision, "updated_at": self.updated_at, "source": self.source,
                "coefficients": self.values}

    @classmethod
    def from_dict(cls, data, station_id=None, unit=None):
        if not isinstance(data, dict):
            raise ValueError("Некорректная запись профиля поправок.")
        station, turbine = str(data.get("station_id", "")), str(data.get("unit", ""))
        if not station or not turbine.isdigit():
            raise ValueError("В профиле поправок не указаны ТЭЦ и номер ГТ.")
        if (station_id is not None and station != station_id) or (unit is not None and turbine != str(unit)):
            raise ValueError("Профиль поправок относится к другой ТЭЦ или ГТ.")
        if data.get("method", METHOD) != METHOD:
            raise ValueError("Методика профиля поправок пока не поддерживается.")
        values = data.get("coefficients", {})
        if not isinstance(values, dict) or set(values) != KEYS:
            missing = sorted(KEYS - set(values)) if isinstance(values, dict) else []
            raise ValueError("Требуются ровно 63 именованных коэффициента поправок. "
                             + ("Не заполнены: " + ", ".join(missing[:5]) if missing else "Проверьте имена полей."))
        coefficients = tuple((field.key, number(values[field.key], f"Коэффициент {field.key}")) for field in FIELDS)
        revision = data.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("Некорректная версия профиля поправок.")
        return cls(station, turbine, coefficients, METHOD, revision,
                   str(data.get("updated_at", "")), str(data.get("source", "")))


def profile_path():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()/".config") / "GTU_Report" / "correction_profiles.json"


def _store():
    path = profile_path()
    if not path.exists():
        return {"schema_version": 1, "profiles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != 1 or not isinstance(data["profiles"], dict):
            raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Не удалось прочитать справочник поправок: {path}") from error


def load_profile(station_id, unit):
    data = _store()["profiles"].get(f"{station_id}|{unit}")
    return None if data is None else CorrectionProfile.from_dict(data, station_id, unit)


def save_profile(profile):
    data = _store()
    key = f"{profile.station_id}|{profile.unit}"
    old = data["profiles"].get(key)
    # Повреждённую запись нельзя молча заменить.
    previous = CorrectionProfile.from_dict(old, profile.station_id, profile.unit) if old is not None else None
    saved = CorrectionProfile.from_dict({**profile.to_dict(),
        "revision": previous.revision + 1 if previous else 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    data["profiles"][key] = saved.to_dict()
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return saved


def embedded_profile(path, station_id, unit):
    with pd.ExcelFile(path, engine="calamine") as book:
        if "Поправки" not in book.sheet_names:
            return None
        frame = book.parse("Поправки", header=None)
    positions = [i for i, value in enumerate(frame.iloc[:,0]) if value == MARKER]
    if not positions:
        return None
    if len(positions) != 1:
        raise ValueError("В книге несколько именованных профилей поправок.")
    try:
        data = json.loads(frame.iat[positions[0], 1])
    except (ValueError, TypeError, IndexError) as error:
        raise ValueError("Повреждён именованный профиль поправок в книге.") from error
    return CorrectionProfile.from_dict(data, station_id, unit)


def resolve_profile(path, station_id, unit):
    if not unit:
        raise ValueError("В имени книги не найден номер ГТ. Укажите, например, ГТ-10.")
    return load_profile(station_id, unit) or embedded_profile(path, station_id, unit)


def require_profile(path, station_id, unit):
    profile = resolve_profile(path, station_id, unit)
    if profile is None:
        raise ValueError(f"Нет именованного профиля поправок для выбранной ТЭЦ, ГТ-{unit}. "
                         "Заполните окно «Поправки ГТ». Адреса старых ячеек автоматически не читаются.")
    return profile


def write_profile(sheet, profile):
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill, Alignment
    rows = [[MARKER, json.dumps(profile.to_dict(), ensure_ascii=False)],
            [f"Поправки ГТ-{profile.unit}: {profile.station_id}, версия {profile.revision}"],
            ["Источник", profile.source], ["Обновлено (UTC)", profile.updated_at],
            ["Именованный коэффициент", "Значение", "Группа / назначение"]]
    for group in GROUPS:
        rows.extend([[field.key, profile.values[field.key], group.title] for field in group.fields])
    for i, row in enumerate(rows):
        cells = []
        for value in row:
            cell = WriteOnlyCell(sheet, value)
            cell.font = Font(name="Calibri", size=11, bold=i in (1,4))
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if i in (1,4):
                cell.fill = PatternFill("solid", fgColor="DFEAF4")
            if isinstance(value, float):
                cell.number_format = "0.000000000000000E+00"
            cells.append(cell)
        sheet.append(cells)
