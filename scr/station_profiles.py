"""Справочники ТЭЦ, тарифов и каналов. Файловый адаптер будущего хранилища БД."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Protocol


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    filename_aliases: tuple[str, ...]
    company_id: str = ""
    name_genitive: str = ""


@dataclass(frozen=True)
class Turbine:
    station_id: str
    number: str
    name: str
    model: str
    calculation_method: str = ""


@dataclass(frozen=True)
class StationTariffs:
    gas_rub_per_nm3: float
    electricity_rub_per_mwh: float
    electricity_cost_rub_per_mwh: float


@dataclass(frozen=True)
class StationInformation:
    station: Station
    company_name: str
    turbines: tuple[Turbine, ...]
    contact_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SensorChannel:
    station_id: str
    unit_number: str
    parameter_id: str
    parameter_name: str
    code: str
    target_column: str
    factor: float


@dataclass(frozen=True)
class DuplicateChannel:
    station_id: str
    derived_code: str
    source_code: str
    factor: float


class StationRepository(Protocol):
    """Контракт хранилища: GUI и импорт не зависят от формата JSON/БД."""

    def list_stations(self) -> tuple[Station, ...]: ...
    def get_station(self, station_id: str) -> Station: ...
    def detect_station(self, filename: str | Path) -> Station | None: ...
    def get_tariffs(self, station_id: str) -> StationTariffs | None: ...
    def save_tariffs(self, station_id: str, tariffs: StationTariffs) -> StationTariffs: ...
    def get_station_information(self, station_id: str) -> StationInformation: ...
    def save_station_contacts(self, contacts: dict, *, unassigned=None, source=None) -> None: ...
    def list_turbines(self, station_id: str) -> tuple[Turbine, ...]: ...
    def get_turbine(self, station_id: str, number: str) -> Turbine: ...
    def detect_turbine(self, filename: str | Path, station_id: str) -> Turbine | None: ...
    def get_channels(self, station_id: str) -> tuple[SensorChannel, ...]: ...
    def get_duplicates(self, station_id: str) -> tuple[DuplicateChannel, ...]: ...


def _normalized_name(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold().replace("ё", "е"))


def unit_number(filename: str | Path) -> str | None:
    numbers = _unit_numbers(filename)
    return next(iter(numbers)) if len(numbers) == 1 else None


def _unit_numbers(filename):
    matches = re.findall(r"(?<![\w])(?:ГТУ?|GTU?)[-\s_]*(\d+[A-Za-zА-Яа-яЁё]?)(?![A-Za-zА-Яа-яЁё0-9])",
                         Path(filename).stem.replace("_", " "), re.I)
    return {match.upper() for match in matches}


def valid_unit_number(value: str) -> bool:
    return bool(re.fullmatch(r"\d+[A-ZА-ЯЁ]?", value))


def catalog_path() -> Path:
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / "config" / "stations.json"
        if external.is_file():
            return external
        return Path(sys._MEIPASS) / "config" / "stations.json"
    return Path(__file__).resolve().parents[1] / "config" / "stations.json"


def tariff_store_path() -> Path:
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'GTU_Report/station_tariffs.json'


def information_store_path() -> Path:
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'GTU_Report/station_information.json'


def _validated_tariffs(record) -> StationTariffs:
    names = ('gas_rub_per_nm3', 'electricity_rub_per_mwh', 'electricity_cost_rub_per_mwh')
    try:
        if any(isinstance(record[name], bool) for name in names):
            raise ValueError()
        values = [float(record[name]) for name in names]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError()
        return StationTariffs(*values)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError('Набор тарифов должен содержать три конечных неотрицательных числа.') from error


def _read_tariff_store(path):
    from json_store import read_json
    data = read_json(path, {'schema_version': 1, 'tariffs': {}})
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1 or not isinstance(data.get('tariffs'), dict):
        raise ValueError('Повреждён пользовательский справочник тарифов; файл не изменён.')
    for key, record in data['tariffs'].items():
        if not key or not isinstance(record, dict):
            raise ValueError('Повреждена запись пользовательского справочника тарифов.')
        _validated_tariffs(record)
    return data


class JsonStationRepository:
    def __init__(self, path: str | Path, *, tariff_store: str | Path | None = None,
                 information_store: str | Path | None = None):
        self.path = Path(path)
        self.tariff_store = Path(tariff_store) if tariff_store is not None else None
        self.information_store = Path(information_store) if information_store is not None else None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self._load(raw)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f"Не удалось прочитать справочник ТЭЦ {self.path}: {error}") from error

    def _load(self, raw: dict) -> None:
        if raw["schema_version"] != 1:
            raise ValueError("Неподдерживаемая версия справочника.")
        self._stations: dict[str, Station] = {}
        self.companies = {row["id"]: row["name"] for row in raw.get("companies", [])}
        station_names: set[str] = set()
        for row in raw["stations"]:
            station = Station(row["id"], row["name"], tuple(row["filename_aliases"]),
                              row.get("company_id", ""), row.get("name_genitive", ""))
            if not isinstance(station.name_genitive, str):
                raise ValueError("Название ТЭЦ в родительном падеже должно быть строкой.")
            if station.company_id and station.company_id not in self.companies:
                raise ValueError("Не найдена компания станции.")
            name_key = _normalized_name(station.name)
            if not station.id or not name_key or station.id in self._stations or name_key in station_names:
                raise ValueError("Пустое или повторное название/ID ТЭЦ.")
            self._stations[station.id] = station
            station_names.add(name_key)
        if not self._stations:
            raise ValueError("Справочник ТЭЦ пуст.")

        self._tariffs: dict[str, StationTariffs] = {}
        for row in raw["tariffs"]:
            key = row["station_id"]
            self.get_station(key)
            if key in self._tariffs:
                raise ValueError(f"Два набора тарифов для ТЭЦ {key}.")
            values = [float(row[name]) for name in (
                "gas_rub_per_nm3", "electricity_rub_per_mwh", "electricity_cost_rub_per_mwh"
            )]
            if any(not math.isfinite(value) or value < 0 for value in values):
                raise ValueError(f"Неверные тарифы для ТЭЦ {key}.")
            self._tariffs[key] = StationTariffs(*values)
        self._turbines: dict[tuple[str, str], Turbine] = {}
        for row in raw.get("turbines", []):
            self.get_station(row["station_id"])
            turbine = Turbine(row["station_id"], str(row["number"]), row["name"],
                              row["model"], row.get("calculation_method", ""))
            key = (turbine.station_id, turbine.number)
            if key in self._turbines or not valid_unit_number(turbine.number) or not turbine.name or not turbine.model:
                raise ValueError("Пустая или повторная запись ГТУ/модели.")
            self._turbines[key] = turbine

        parameters = {}
        for row in raw["sensor_parameters"]:
            key = row["id"]
            if key in parameters or not re.fullmatch(r"[A-Z]{1,3}", row["target_column"]):
                raise ValueError(f"Неверный параметр датчика {key}.")
            parameters[key] = row
        self._channels: list[SensorChannel] = []
        seen = set()
        seen_parameters = set()
        for row in raw["sensor_channels"]:
            self.get_station(row["station_id"])
            parameter = parameters[row["parameter_id"]]
            key = (row["station_id"], str(row["unit_number"]), row["code"].casefold())
            parameter_key = (row["station_id"], str(row["unit_number"]), parameter["target_column"])
            factor = float(row["factor"])
            if key in seen or parameter_key in seen_parameters or not row["code"] or not math.isfinite(factor) or factor == 0:
                raise ValueError(f"Неверный или повторный канал {row['code']}.")
            seen.add(key)
            seen_parameters.add(parameter_key)
            self._channels.append(SensorChannel(
                row["station_id"], str(row["unit_number"]), row["parameter_id"],
                parameter["name"], row["code"], parameter["target_column"], factor,
            ))
        self._duplicates: list[DuplicateChannel] = []
        for row in raw.get("duplicate_channels", []):
            self.get_station(row["station_id"])
            factor = float(row["factor"])
            if not math.isfinite(factor) or factor == 0:
                raise ValueError("Неверный коэффициент дублирующего канала.")
            if not any(channel.station_id == row["station_id"] and
                       channel.code == row["source_code"] for channel in self._channels):
                raise ValueError(f"Не найден исходный канал {row['source_code']}.")
            self._duplicates.append(DuplicateChannel(
                row["station_id"], row["derived_code"], row["source_code"], factor,
            ))

    def list_stations(self) -> tuple[Station, ...]:
        return tuple(self._stations.values())

    def get_station(self, station_id: str) -> Station:
        try:
            return self._stations[station_id]
        except KeyError as error:
            raise ValueError(f"Неизвестная ТЭЦ: {station_id!r}. Выберите ТЭЦ из списка.") from error

    def get_station_information(self, station_id: str) -> StationInformation:
        from station_information import read_information
        station = self.get_station(station_id)
        names = (read_information(self.information_store)['contacts'].get(station_id, [])
                 if self.information_store is not None else [])
        return StationInformation(station, self.companies.get(station.company_id, ''),
                                  self.list_turbines(station_id), tuple(names))

    def save_station_contacts(self, contacts: dict, *, unassigned=None, source=None) -> None:
        from station_information import update_contacts
        if self.information_store is None:
            raise ValueError('Пользовательское хранилище сведений о ТЭЦ не настроено.')
        for station_id in contacts:
            self.get_station(station_id)
        update_contacts(self.information_store, contacts, unassigned=unassigned, source=source)

    def detect_station(self, filename: str | Path) -> Station | None:
        name = _normalized_name(Path(filename).stem)
        matches = [(max((len(_normalized_name(alias)) for alias in
                    (station.name, *station.filename_aliases)
                    if _normalized_name(alias) and _normalized_name(alias) in name), default=0), station)
                   for station in self.list_stations()]
        longest = max(score for score, _ in matches)
        best = [station for score, station in matches if score == longest and score > 0]
        return best[0] if len(best) == 1 else None

    def get_tariffs(self, station_id: str) -> StationTariffs | None:
        self.get_station(station_id)
        if self.tariff_store is not None:
            record = _read_tariff_store(self.tariff_store)['tariffs'].get(station_id)
            if record is not None:
                return _validated_tariffs(record)
        return self._tariffs.get(station_id)

    def save_tariffs(self, station_id: str, tariffs: StationTariffs) -> StationTariffs:
        """Update only this station after a successful calculation, atomically."""
        from json_store import transaction, write_json
        self.get_station(station_id)
        if self.tariff_store is None:
            raise ValueError('Пользовательское хранилище тарифов не настроено.')
        validated = _validated_tariffs(asdict(tariffs))
        with transaction():
            data = _read_tariff_store(self.tariff_store)
            data['tariffs'][station_id] = {**asdict(validated),
                'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'source': 'successful_calculation'}
            write_json(self.tariff_store, data)
        return validated

    def list_turbines(self, station_id: str) -> tuple[Turbine, ...]:
        self.get_station(station_id)
        return tuple(row for row in self._turbines.values() if row.station_id == station_id)

    def get_turbine(self, station_id: str, number: str) -> Turbine:
        self.get_station(station_id)
        try:
            return self._turbines[station_id, str(number)]
        except KeyError as error:
            raise ValueError(f"ГТУ-{number} отсутствует в справочнике выбранной станции.") from error

    def detect_turbine(self, filename: str | Path, station_id: str) -> Turbine | None:
        candidates = _unit_numbers(filename)
        matches = [row for row in self.list_turbines(station_id) if row.number in candidates]
        return matches[0] if len(matches) == 1 else None

    def get_channels(self, station_id: str) -> tuple[SensorChannel, ...]:
        self.get_station(station_id)
        return tuple(row for row in self._channels if row.station_id == station_id)

    def get_duplicates(self, station_id: str) -> tuple[DuplicateChannel, ...]:
        self.get_station(station_id)
        return tuple(row for row in self._duplicates if row.station_id == station_id)


@lru_cache(maxsize=1)
def get_station_repository() -> StationRepository:
    return JsonStationRepository(catalog_path(), tariff_store=tariff_store_path(),
                                 information_store=information_store_path())


def resolve_station(book_path: str | Path, station_id: str | None = None,
                    repository: StationRepository | None = None) -> Station | None:
    repository = repository or get_station_repository()
    return (repository.get_station(station_id) if station_id is not None
            else repository.detect_station(book_path))


def sensor_target_columns(station_id: str | None = None,
                          repository: StationRepository | None = None) -> set[str]:
    repository = repository or get_station_repository()
    stations = (repository.get_station(station_id),) if station_id else repository.list_stations()
    return {channel.target_column for station in stations
            for channel in repository.get_channels(station.id)}
