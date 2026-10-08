# -*- coding: utf-8 -*-
"""Общая загрузка и первичная подготовка данных ГТУ.

Книга открывается один раз через calamine. Оба расчёта получают из этого
модуля свои представления одного и того же набора строк.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


COLUMN_MAP = {
    "дата": "Дата", "date": "Дата", "time": "Дата", "дата/время": "Дата",
    "pатм.": "Pатм.", "pатм": "Pатм.", "ратм": "Pатм.", "pатм, па": "Pатм.",
    "тнк": "Тнк", "tнк": "Тнк", "тнк, °с": "Тнк",
    "pнк": "Pнк", "рнк": "Pнк", "pнк, мбар": "Pнк",
    "вна": "ВНА",
    "ткк": "Ткк", "tкк": "Ткк", "ткк, °с": "Ткк",
    "pкк": "Ркк", "ркк": "Ркк", "ркк, бар": "Ркк",
    "nприв": "Nприв", "nприв, мвт": "Nприв", "n прив": "Nприв",
    "nприв,мвт": "Nприв", "nприв (мвт)": "Nприв",
    "приведенная мощность": "Nприв", "приведённая мощность": "Nприв",
    "вприв": "Вприв", "bприв, нм3/ч": "Вприв", "bприв, нм³/ч": "Вприв",
    "вприв, нм3/ч": "Вприв", "вприв, нм³/ч": "Вприв", "bприв,нм3/ч": "Вприв",
    "приведенный расход газа": "Вприв", "приведённый расход газа": "Вприв",
    "приведенный расход": "Вприв", "приведённый расход": "Вприв",
    "расход газа": "Расход газа",
    "bприв": "bприв", "b прив": "bприв",
    "pгаз": "Pгаз", "pгаз, мпа": "Pгаз", "ргаз": "Pгаз",
    "тгаз": "Тгаз", "tгаз": "Тгаз", "tгаз, с": "Тгаз",
    "qнр": "Qнр", "qнр, мдж/м3": "Qнр", "qнр, мдж/м³": "Qнр",
    "вло": "ВЛО", "вло, па": "ВЛО",
    "фго": "ФГО", "фго, па": "ФГО",
    "фто": "ФТО", "фто, па": "ФТО",
    "фго+фто": "ФГО+ФТО", "фго+фто, па": "ФГО+ФТО",
    # Для графика нужна именно мощность N, МВт. В книге есть и другие
    # колонки, начинающиеся с N, например обороты ротора.
    "n, мвт": "N",
}
COLUMN_MAP = {key.strip().lower(): value for key, value in COLUMN_MAP.items()}


SHORT_NAMES = {
    "date": ["Дата"],
    "t": ["Тнк"],
    "vna": ["ВНА"],
    "tkk": ["Ткк"],
    "p_atm_pa": ["Pатм."],
    "p_nk_pa": ["Pнк"],
    "p_kk_mpa": ["Ркк"],
    "power": ["Nприв"],
    "fuel": ["Вприв", "Расход газа"],
    "fuel_specific": ["bприв"],
    "gas_pressure": ["Pгаз"],
    "gas_temperature": ["Тгаз"],
    "q_lower": ["Qнр"],
    "vlo": ["ВЛО"],
    "fgo": ["ФГО"],
    "fto": ["ФТО"],
    "fgo_fto": ["ФГО+ФТО"],
    "power_n": ["N"],
}


REQUIRED_NAMES = [
    "date", "t", "vna", "tkk", "p_atm_pa", "p_nk_pa", "p_kk_mpa",
    "power", "fuel",
]


def _clean_header(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip().lower()


def _short_header(value: str) -> str:
    return re.split(r",", value, maxsplit=1)[0].strip()


def _make_unique_headers(headers: list) -> list:
    seen: dict[str, int] = {}
    result = []
    for header in headers:
        if header in seen:
            seen[header] += 1
            result.append(f"{header}_{seen[header]}")
        else:
            seen[header] = 0
            result.append(header)
    return result


def _map_headers(raw_headers: list) -> tuple[list, list]:
    mapped = []
    unknown = []
    for raw in raw_headers:
        full = _clean_header(raw)
        short = _short_header(full)
        if full in COLUMN_MAP:
            mapped.append(COLUMN_MAP[full])
        elif short in COLUMN_MAP:
            mapped.append(COLUMN_MAP[short])
        else:
            mapped.append(full or "unnamed")
            if full:
                unknown.append(str(raw).replace("\n", " "))
    return _make_unique_headers(mapped), unknown


def _find_header_row(head: pd.DataFrame, min_matches: int = 2) -> int | None:
    keys = set(COLUMN_MAP)
    for index, row in head.iterrows():
        values = set()
        for value in row:
            full = _clean_header(value)
            if full:
                values.add(full)
                values.add(_short_header(full))
        if len(values.intersection(keys)) >= min_matches:
            return int(index)
    return None


def load_source_data(file_path: str | Path, sheet_name: str = "Данные") -> pd.DataFrame:
    """Открывает книгу один раз и возвращает общий канонический DataFrame."""
    path = Path(file_path)
    print(f"Загрузка данных: {path.name}")

    with pd.ExcelFile(path, engine="calamine") as workbook:
        first_sheet = workbook.sheet_names[0]
        if str(first_sheet).strip() != sheet_name:
            raise ValueError(
                f"Первый лист книги называется '{first_sheet}', "
                f"а ожидается '{sheet_name}'."
            )

        head = workbook.parse(sheet_name, header=None, nrows=25)
        header_row = _find_header_row(head)
        if header_row is None:
            raise ValueError(
                f"Не найдена строка шапки на листе '{sheet_name}' "
                f"в файле {path.name}"
            )

        raw_headers = workbook.parse(
            sheet_name, header=None, nrows=header_row + 1
        ).iloc[header_row].tolist()
        raw = workbook.parse(
            sheet_name, header=None, skiprows=header_row + 1
        )

    min_cols = min(raw.shape[1], len(raw_headers))
    raw = raw.iloc[:, :min_cols].copy()
    mapped_headers, unknown = _map_headers(raw_headers[:min_cols])
    raw.columns = mapped_headers
    raw = raw.dropna(how="all")

    if unknown:
        print(f"Нераспознанные столбцы: {', '.join(unknown)}")

    result = pd.DataFrame(index=raw.index)
    for short_name, canonical_names in SHORT_NAMES.items():
        for canonical_name in canonical_names:
            if canonical_name in raw.columns:
                result[short_name] = raw[canonical_name]
                break

    missing = [name for name in REQUIRED_NAMES if name not in result.columns]
    if missing:
        raise ValueError(
            f"Не найдены обязательные колонки: {missing}. "
            f"Распознанные заголовки: {list(raw.columns)}"
        )

    # Колонка A в исходной книге не имеет заголовка. Сохраняем её последнее
    # числовое значение для контрольной проверки, а рабочие часы считаем
    # самостоятельно по физическому порядку строк с шагом 0.5 часа.
    if raw.shape[1] > 0:
        result["hours_input"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
    else:
        result["hours_input"] = np.nan
    result["hours"] = result.index.to_numpy(dtype=float) * 0.5

    print(f"Загружено строк: {len(result)}")
    return result.reset_index(drop=True)


def prepare_rh_data(source: pd.DataFrame) -> pd.DataFrame:
    """Подготавливает общий набор данных для расходной характеристики."""
    columns = ["date", "power", "fuel"]
    columns += [
        name for name in [
            "fuel_specific", "gas_pressure", "gas_temperature", "q_lower",
            "hours", "hours_input", "vlo", "fgo", "fto", "fgo_fto", "vna",
            "power_n"
        ]
        if name in source.columns
    ]
    result = source[columns].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in result.columns[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def prepare_vna_data(source: pd.DataFrame) -> pd.DataFrame:
    """Приводит давления и типы к формату расчёта ВНА."""
    result = source.copy()
    p_atm = pd.to_numeric(result["p_atm_pa"], errors="coerce")
    p_nk = pd.to_numeric(result["p_nk_pa"], errors="coerce")
    p_kk = pd.to_numeric(result["p_kk_mpa"], errors="coerce")
    ratio = (p_nk / p_atm).median()

    if ratio > 0.5:
        inlet_pa = p_nk
        print(f"Pнк — абсолютное давление на входе (Pнк/Pатм = {ratio:.3f})")
    else:
        inlet_pa = p_atm - p_nk
        print(
            "Pнк — потеря давления на входе, абсолютное = Pатм − Pнк "
            f"(Pнк/Pатм = {ratio:.4f})"
        )

    result["p"] = inlet_pa / 100.0
    result["pkk"] = p_kk * 10.0
    result = result.drop(columns=["p_atm_pa", "p_nk_pa", "p_kk_mpa"])
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in ["t", "p", "vna", "tkk", "pkk"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(
        subset=["date", "t", "p", "vna", "tkk", "pkk"]
    ).reset_index(drop=True)
