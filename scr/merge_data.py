# -*- coding: utf-8 -*-
"""Шаг 1. Сборка и объединение отчётных Excel-файлов ТЭЦ в один файл.

Логика объединения перенесена из Predictive_analytics_new.py БЕЗ изменений:
читает все .xlsx/.xlsm из папки INPUT_DIR, приводит каждый файл к единой
канонической схеме (лист 'Данные' или 'Расчет'), склеивает, убирает
дубликаты по времени и сохраняет результат.

ЗАПУСК:
    py src/merge_data.py

НАСТРОЙКИ (в самом низу файла, блок `if __name__ == "__main__"`):
    INPUT_DIR   — папка с исходными Excel-файлами (откуда брать данные);
    OUTPUT_PATH — куда сохранить результат: конкретный файл "*.xlsx"
                  ИЛИ папка (тогда в ней будет создан merged_data.xlsx).
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("kvou_predictive")

# =============================================================================
# 1. СХЕМА И СЛОВАРЬ МАППИНГА КОЛОНОК
# =============================================================================
COLUMN_MAP: dict[str, str] = {
    # БАЗОВЫЕ ПОКАЗАТЕЛИ
    "дата": "Дата", "date": "Дата", "time": "Дата", "дата/время": "Дата",

    # Мощность
    "мощность": "Мощность", "nакт": "Мощность", "n, мвт": "Мощность", "n мвт": "Мощность", "n": "Мощность",
    "nприв": "Nприв", "nприв, мвт": "Nприв",
    # варианты написания «приведённой мощности»
    "n прив": "Nприв", "nприв,мвт": "Nприв", "nприв (мвт)": "Nприв",
    "приведенная мощность": "Nприв", "приведённая мощность": "Nприв",
    "Приведенная мощность": "Nприв", "Приведённая мощность": "Nприв",

    # Обороты (не путать с мощностью 'N', если она записана как 'n')
    "n, гц": "n", "n гц": "n", "n,гц": "n", "nгц": "n", "n, об/мин": "n",

    # Давление
    "pатм.": "Pатм.", "pатм": "Pатм.", "ратм": "Pатм.", "pатм, па": "Pатм.",
    "pнк": "Pнк", "рнк": "Pнк", "pнк, мбар": "Pнк",
    "δpнк": "Δpнк", "общий": "Δpнк", "δpнк, па": "Δpнк", "перепад давления": "Δpнк",
    "давление ух.газов": "Давление ух.газов", "давление ух.газов, кпа": "Давление ух.газов",
    "pкк": "Ркк", "ркк": "Ркк", "ркк, бар": "Ркк",
    "pгаз": "Ргаз", "ргаз": "Ргаз", "pгаза,": "Ргаз", "pгаза": "Ргаз", "p газа": "Ргаз",

    # Температура
    "токр.воздуха": "Токр.воздуха", "tокр.воздуха": "Токр.воздуха", "tатм": "Токр.воздуха",
    "токр, °с": "Токр.воздуха", "токр": "Токр.воздуха",
    "тнк": "Тнк", "tнк": "Тнк", "тнк, °с": "Тнк",
    "ткк": "Ткк", "tкк": "Ткк", "ткк, °с": "Ткк",
    "тгаз": "Тгаз", "температура газа": "Тгаз", "tгаз": "Тгаз", "тг": "Тгаз",
    "tгаза, °с": "Тгаз", "tгаза": "Тгаз",
    "татк": "Татк", "tатк": "Татк", "татк, °с": "Татк",
    "δtнв_нк": "Δtнв_нк",

    # Влажность
    "влажность нв": "Влажность_нв", "влажность_нв": "Влажность_нв", "φатм": "Влажность_нв", "ф, %": "Влажность_нв", "ф": "Влажность_нв",
    "влажность нк": "Влажность_нк", "влажность_нк": "Влажность_нк", "φнк": "Влажность_нк", "ф нк, %": "Влажность_нк", "ф нк": "Влажность_нк",

    # Прочее (Расход, Плотность, КВОУ)
    "расход газа": "Расход газа", "вг": "Расход газа", "b, нм3/ч": "Расход газа", "b": "Расход газа",
    "плотность нк": "Плотность нк", "ρнк": "Плотность нк", "ρ нк, кг/м3": "Плотность нк", "ρ нк": "Плотность нк",

    "вло": "ВЛО", "вло, па": "ВЛО",
    "фго": "ФГО", "фго, па": "ФГО",
    "фто": "ФТО", "фто, па": "ФТО",
    "πк": "πк", "вна": "ВНА", "эчэ": "ЭЧЭ", "наработка": "Наработка",

    "dpлев": "dPлев", "dpср": "dPср", "dpправ": "dPправ",
    "риу": "Риу",
    "тлев": "Тлев", "тср": "Тср", "тправ": "Тправ",
    "φлев": "φлев", "φср": "φср", "φправ": "φправ",
    "dиу": "dиу", "d": "d", "dатм": "d",
    "cos(φ)": "cos(φ)", "cosф": "cos(φ)",
    "bприв": "bприв", "вприв": "Вприв", "bприв, нм3/ч": "Вприв",
    # варианты написания «приведённого расхода газа» (лат. B / кир. В, нм³/ч)
    "bприв, нм³/ч": "Вприв", "вприв, нм3/ч": "Вприв", "вприв, нм³/ч": "Вприв",
    "b прив": "Вприв", "bприв,нм3/ч": "Вприв",
    "приведенный расход газа": "Вприв", "приведённый расход газа": "Вприв",
    "приведенный расход": "Вприв", "приведённый расход": "Вприв",
    "qнр": "Qнр",

    "hнк": "hнк", "hкк": "hкк", "hух, кдж/кг": "hух", "hух": "hух",
    "перерасход": "Перерасход",
}
COLUMN_MAP = {k.strip().lower(): v for k, v in COLUMN_MAP.items()}

CANONICAL_SCHEMA: list[str] = [
    "Дата", "Наработка", "Мощность", "Pатм.", "Pнк", "Δpнк", "Δtнв_нк", "πк", "ВЛО",
    "ВНА", "Влажность_нв", "Влажность_нк", "Давление ух.газов", "Плотность нк",
    "Расход газа", "Ргаз", "Тгаз", "Ткк", "Ркк", "Татк", "Тнк", "Токр.воздуха",
    "ФГО", "ФТО", "ЭЧЭ", "d", "n", "hнк", "hкк",
    "dPлев", "dPср", "dPправ", "Риу", "Тлев", "Тср", "Тправ",
    "φлев", "φср", "φправ", "dиу", "cos(φ)", "Nприв", "Вприв", "bприв",
]


# =============================================================================
# 2. ЗАГРУЗКА И ОБЪЕДИНЕНИЕ EXCEL-ФАЙЛОВ
# =============================================================================
def make_unique_headers(headers: list) -> list:
    seen: dict[str, int] = {}
    unique_headers = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            unique_headers.append(h)
    return unique_headers


def normalize_and_map_headers(raw_headers: list, column_map: dict) -> tuple[list, list]:
    mapped_headers = []
    unmapped_raw = []
    for col in raw_headers:
        col_str = "" if (col is None or pd.isna(col)) else str(col).strip()

        clean_full = re.sub(r"\s+", " ", col_str.replace("\n", " ")).strip().lower()
        clean_short = re.split(r"[,]", clean_full)[0].strip()

        if clean_full in column_map:
            mapped_headers.append(column_map[clean_full])
        elif clean_short in column_map:
            mapped_headers.append(column_map[clean_short])
        else:
            mapped_headers.append(clean_full if clean_full else "unnamed")
            if clean_full:
                unmapped_raw.append(col_str.replace("\n", " "))

    return make_unique_headers(mapped_headers), unmapped_raw


def find_header_row_by_map(
    file_path: Path, sheet_name: str, column_map: dict, min_matches: int = 2, max_rows: int = 25
) -> int | None:
    try:
        df_head = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=max_rows, engine="calamine")
        map_keys = set(column_map.keys())
        for idx, row in df_head.iterrows():
            vals = set()
            for v in row:
                if pd.notna(v):
                    v_str = str(v).strip().lower()
                    clean_full = re.sub(r"\s+", " ", v_str.replace("\n", " ")).strip()
                    clean_short = re.split(r"[,]", clean_full)[0].strip()
                    vals.add(clean_full)
                    vals.add(clean_short)
            if len(vals.intersection(map_keys)) >= min_matches:
                return idx
    except Exception as e:
        log.error("Ошибка поиска шапки в %s (лист '%s'): %s", file_path.name, sheet_name, e)
    return None


def process_single_file(file_path: Path, column_map: dict, target_schema: list) -> tuple[pd.DataFrame | None, int]:
    try:
        xl = pd.ExcelFile(file_path, engine="calamine")
        available_sheets = xl.sheet_names
        sheet_map = {str(s).strip().lower(): s for s in available_sheets}

        if "данные" in sheet_map:
            target_sheet = sheet_map["данные"]
        elif "расчет" in sheet_map:
            target_sheet = sheet_map["расчет"]
        else:
            # Читаем только файлы с листом 'Данные' или 'Расчет', остальные пропускаем (данные из них не нужны).
            log.warning("⚠️ Пропуск %s: нет листов 'Данные' или 'Расчет'. Доступны: %s", file_path.name, available_sheets)
            return None, 0

        log.info("🔍 %s: выбран лист '%s' из %d доступных.", file_path.name, target_sheet, len(available_sheets))

        header_row = find_header_row_by_map(file_path, target_sheet, column_map)
        if header_row is None:
            log.warning("⚠️ Шапка не найдена на листе '%s' в файле %s", target_sheet, file_path.name)
            return None, 0

        df_head = pd.read_excel(file_path, sheet_name=target_sheet, header=None, nrows=header_row + 1, engine="calamine")
        raw_headers = df_head.iloc[header_row].tolist()

        df = pd.read_excel(file_path, sheet_name=target_sheet, header=None, engine="calamine", skiprows=header_row + 1)
        min_cols = min(df.shape[1], len(raw_headers))
        df = df.iloc[:, :min_cols]
        raw_headers = raw_headers[:min_cols]

        file_headers, unmapped_headers = normalize_and_map_headers(raw_headers, column_map)

        if unmapped_headers:
            log.warning("❓ Нераспознанные столбцы в %s: %s", file_path.name, ", ".join(unmapped_headers))

        df.columns = file_headers
        df = df.dropna(how="all")
        df = df.reindex(columns=target_schema)

        if "Дата" in df.columns and not df.empty:
            df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
            initial_count = len(df)
            df = df.dropna(subset=["Дата"])
            if initial_count - len(df) > 0:
                log.info("  🗑️ %s: удалено %d строк с невалидной датой", file_path.name, initial_count - len(df))

        return df, len(df)

    except Exception as e:
        log.error("❌ Ошибка при обработке %s: %s", file_path.name, e)
        return None, 0


def merge_excel_files_parallel(
    folder_path: str,
    output_excel_path: str,
    column_map: dict | None = None,
    target_schema: list | None = None,
    max_workers: int = 8,
    dedup_round_freq: str = "10min",
) -> pd.DataFrame:
    """Читает все .xlsx/.xlsm файлы из папки, приводит к единой схеме и склеивает.

    ИСПРАВЛЕНО (найдено статическим анализом, pylint W0102): изменяемые объекты
    (dict/list) в качестве значений по умолчанию — известная ловушка Python:
    если их случайно мутировать внутри функции, повреждается общий объект для
    всех последующих вызовов. Здесь мутации не было, но защититься от этого
    в будущем стоит копейки — заменили на None + подстановку внутри функции.
    """
    column_map = COLUMN_MAP if column_map is None else column_map
    target_schema = CANONICAL_SCHEMA if target_schema is None else target_schema
    folder = Path(folder_path)
    all_files = sorted(list(folder.glob("*.xlsx")) + list(folder.glob("*.xlsm")))

    if not all_files:
        log.warning("Файлы Excel не найдены в %s", folder)
        return pd.DataFrame()

    log.info("=" * 60)
    log.info("🚀 СТАРТ ОБРАБОТКИ (%d файлов найдено)", len(all_files))
    log.info("=" * 60)

    all_dfs = []
    file_stats: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_file, f, column_map, target_schema): f for f in all_files}
        for future in as_completed(futures):
            f_path = futures[future]
            df, count = future.result()
            if df is not None and not df.empty:
                all_dfs.append(df)
                file_stats[f_path.name] = count

    if not all_dfs:
        log.warning("⚠️ Нет данных для объединения.")
        return pd.DataFrame()

    final_df = pd.concat(all_dfs, ignore_index=True, sort=False)

    if "Дата" in final_df.columns:
        final_df = final_df.sort_values("Дата").reset_index(drop=True)
        initial_len = len(final_df)

        # Умное удаление дубликатов: округляем время, чтобы поймать рассинхрон в секундах/минутах
        rounded_dates = final_df["Дата"].dt.round(dedup_round_freq)
        final_df = final_df.loc[~rounded_dates.duplicated(keep="first")].reset_index(drop=True)

        dedup_dropped = initial_len - len(final_df)
        if dedup_dropped > 0:
            log.info("👯 Удалено дубликатов по времени (с учётом погрешности): %d", dedup_dropped)

    total_expected = sum(file_stats.values())
    total_actual = len(final_df)
    log.info("%s", "=" * 60)
    log.info("📊 ИТОГОВАЯ СТАТИСТИКА ЦЕЛОСТНОСТИ ДАННЫХ:")
    for name, count in file_stats.items():
        log.info(" • %s: %d строк", name, count)
    log.info("Сумма строк во всех файлах: %d | Итого строк: %d", total_expected, total_actual)

    out_path = Path(output_excel_path)
    if out_path.name:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        final_df.to_excel(out_path, index=False, sheet_name="Данные")
        log.info("✅ Итоговый файл записан в: %s", out_path.resolve())

    return final_df


# =============================================================================
# 3. НАСТРОЙКИ ЗАПУСКА
# =============================================================================
def resolve_output_file(output_path: str, default_name: str = "merged_data.xlsx") -> Path:
    """Определяет итоговый путь к файлу.

    Если output_path указывает на файл (расширение .xlsx/.xlsm) — берём его как есть.
    Если на папку — создаём в ней файл с именем default_name.
    """
    p = Path(output_path)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        return p
    return p / default_name


if __name__ == "__main__":
    # -------------------------------------------------------------------------
    # 1) ОТКУДА БРАТЬ ДАННЫЕ: папка с исходными Excel-файлами (.xlsx/.xlsm).
    # -------------------------------------------------------------------------
    INPUT_DIR = "C:/Users/user/Desktop/Predictive Analytics/Zatonskaya/GT-1/Input_new"

    # -------------------------------------------------------------------------
    # 2) КУДА СОХРАНИТЬ ОБЪЕДИНЁННЫЙ ФАЙЛ.
    #    Вариант А — конкретный файл:  OUTPUT_PATH = "Output/Output.xlsx"
    #    Вариант Б — папка:            OUTPUT_PATH = "Output"
    #                                  (сохранится "Output/merged_data.xlsx")
    # -------------------------------------------------------------------------
    OUTPUT_PATH = "C:/Users/user/Desktop/Predictive Analytics/Zatonskaya/GT-1/Output/Output.xlsx"

    output_file = resolve_output_file(OUTPUT_PATH)
    log.info("📥 Папка-источник: %s", Path(INPUT_DIR).resolve())
    log.info("📤 Файл-результат: %s", output_file.resolve())

    merge_excel_files_parallel(INPUT_DIR, str(output_file))
