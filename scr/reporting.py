# -*- coding: utf-8 -*-
"""Подготовка JSON и генерация Word-отчёта.

Модуль отделён от расчётных алгоритмов. Расчёт передаёт сюда итоговые
таблицы после подтверждения периодов. Модуль превращает их в JSON-контекст
для docxtpl и может сразу отрендерить выбранный шаблон в DOCX.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from project_paths import OUTPUT_DIR


if getattr(sys, "frozen", False):
    # Рабочие шаблоны лежат рядом с EXE. Если внешнюю папку не передали,
    # используем копию, встроенную PyInstaller в _internal.
    ROOT = Path(sys.executable).resolve().parent
    _bundle_root = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    _module_path = Path(__file__).resolve()
    ROOT = (
        _module_path.parents[2]
        if _module_path.parent.name == "src"
        else _module_path.parents[1]
    )
    _bundle_root = ROOT
_external_template_dir = ROOT / "word_auto" / "templates"
DEFAULT_TEMPLATE_DIR = (
    _external_template_dir
    if _external_template_dir.exists()
    else _bundle_root / "word_auto" / "templates"
)
DEFAULT_TEMPLATE = DEFAULT_TEMPLATE_DIR / "template_mapped.docx"
DEFAULT_REPORT_DIR = OUTPUT_DIR
DEFAULT_DATA_FILE = ROOT / "data" / "report_runs" / "latest.json"
NOMINAL_VNA_PERCENT = 80.0


class PeriodCollection(list):
    """Список периодов с совместимостью для обращений ``periods.p1``.

    Основной формат JSON — массив, поэтому обращения ``periods[0]`` и
    циклы по ``periods`` остаются рабочими. В Word-шаблонах также встречается
    старый короткий синтаксис ``periods.p1``; он означает первый период.
    """

    def __getattr__(self, name: str):
        if name.startswith("p") and name[1:].isdigit():
            position = int(name[1:]) - 1
            if 0 <= position < len(self):
                return self[position]
            return None
        raise AttributeError(name)


ORDINAL_GENITIVE = {
    1: "первого",
    2: "второго",
    3: "третьего",
    4: "четвёртого",
}
ORDINAL_PREPOSITIONAL = {
    1: "первом",
    2: "втором",
    3: "третьем",
    4: "четвёртом",
}
PERIOD_INTRO = {
    1: "В первом",
    2: "Во втором",
    3: "В третьем",
    4: "В четвёртом",
}
DEGRADATION_PERIOD = {
    1: "в первом",
    2: "во втором",
    3: "в третьем",
    4: "в четвёртом",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (float, np.floating)):
        return not math.isfinite(float(value))
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _number(value: Any, decimals: int = 3) -> str:
    """Форматирует число для Word с запятой и без лишних нулей."""

    if _is_missing(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    text = f"{number:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _fixed_number(value: Any, decimals: int = 2) -> str:
    """Форматирует число с обязательными знаками после запятой."""
    if _is_missing(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    return f"{number:.{decimals}f}".replace(".", ",")


def _money(value: Any) -> str:
    if _is_missing(value):
        return "—"
    try:
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def _date_value(value: Any, short: bool = False) -> str:
    if _is_missing(value):
        return "—"
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    return timestamp.strftime("%d.%m.%Y" if short else "%d-%m-%Y %H:%M")


def _get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _find_boundary(table: pd.DataFrame | None, period_number: int, marker: str):
    if table is None or table.empty or "Период" not in table.columns:
        return None
    for _, row in table.iterrows():
        period_value = str(row.get("Период", ""))
        if period_value.startswith(f"{period_number} ") and marker in period_value:
            return row
    return None


def _boundary_context(row: Any) -> dict[str, str]:
    return {
        "date": _date_value(_get(row, "дата")),
        "date_short": _date_value(_get(row, "дата"), short=True),
        "vlo_pa": _number(_get(row, "ВЛО"), 1),
        "fgo_pa": _number(_get(row, "ФГО"), 1),
        "fto_pa": _number(_get(row, "ФТО"), 1),
        "fgo_fto_pa": _number(_get(row, "ФГО+ФТО"), 1),
        "vna_percent": _number(_get(row, "ВНА"), 1),
        "n_priv_mw": _number(_get(row, "Nприв"), 3),
        "b_priv": _number(_get(row, "bприв"), 3),
        "power_n_mw": _number(_get(row, "N"), 3),
    }


def _delta_context(row: Any) -> dict[str, Any]:
    def clipped(value: Any, direction: int) -> float | None:
        if _is_missing(value):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        result = max(direction * number, 0.0)
        return 0.0 if result == 0 else result

    # Регрессия хранит знаковые изменения. Для текста отчёта снижение
    # мощности и рост удельного расхода показываются после отсечки улучшений.
    n_priv = clipped(_get(row, "ΔNприв до отсечки", _get(row, "ΔNприв")), -1)
    b_priv = clipped(_get(row, "Δbприв до отсечки", _get(row, "Δbприв")), 1)
    n_percent = clipped(_get(row, "ΔNприв, %"), -1)
    b_percent = clipped(_get(row, "Δbприв, %"), 1)
    return {
        "n_priv": _number(n_priv, 3),
        "n_priv_percent": _fixed_number(n_percent),
        "b_priv": _number(b_priv, 3),
        "b_priv_percent": _fixed_number(b_percent),
        "show_no_degradation_text": (
            (n_priv is not None and round(n_priv, 3) == 0)
            or (b_priv is not None and round(b_priv, 3) == 0)
        ),
        "eta_gtu_pp": _number(_get(row, "Δη, п.п."), 3),
        "eta_gtu_percent": _number(_get(row, "Δη, %"), 3),
    }


def _vna_top_context(table: Any) -> dict[str, Any]:
    empty = {
        "rank": "—",
        "interval": "—",
        "count": "—",
        "share_percent": "—",
        "delta_t_c": "—",
        "delta_p_mbar": "—",
        "delta_days": "—",
        "delta_eta_pp": "—",
        "point_1": {
            "date": "—", "t_nk_c": "—", "p_nk_mbar": "—",
            "vna_percent": "—", "t_kk_c": "—", "pi_k": "—",
            "eta_percent": "—",
        },
        "point_2": {
            "date": "—", "t_nk_c": "—", "p_nk_mbar": "—",
            "vna_percent": "—", "t_kk_c": "—", "pi_k": "—",
            "eta_percent": "—",
        },
    }
    if table is None:
        return empty
    if isinstance(table, pd.DataFrame):
        if table.empty:
            return empty
        row = table.iloc[0]
    else:
        rows = list(table)
        if not rows:
            return empty
        row = rows[0]

    def num(key: str, decimals: int = 3) -> str:
        return _number(_get(row, key), decimals)

    def dt(key: str) -> str:
        return _date_value(_get(row, key))

    return {
        "rank": num("rank", 0),
        "interval": str(_get(row, "vna_interval", "—")),
        "count": num("count", 0),
        "share_percent": num("share_percent", 2),
        "delta_t_c": num("delta_t", 2),
        "delta_p_mbar": num("delta_p", 2),
        "delta_days": num("delta_days", 2),
        "delta_eta_pp": num("delta_eta", 2),
        "point_1": {
            "date": dt("date_1"),
            "t_nk_c": num("t_1", 2),
            "p_nk_mbar": num("p_1", 2),
            "vna_percent": num("vna_1", 2),
            "t_kk_c": num("tkk_1", 2),
            "pi_k": num("pi_k_1", 3),
            "eta_percent": num("eta_1", 3),
        },
        "point_2": {
            "date": dt("date_2"),
            "t_nk_c": num("t_2", 2),
            "p_nk_mbar": num("p_2", 2),
            "vna_percent": num("vna_2", 2),
            "t_kk_c": num("tkk_2", 2),
            "pi_k": num("pi_k_2", 3),
            "eta_percent": num("eta_2", 3),
        },
    }


def _last_numeric(data: Any, column: str) -> float | None:
    if data is None or not hasattr(data, "columns") or column not in data.columns:
        return None
    values = pd.to_numeric(data[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _economics_total(table: pd.DataFrame | None) -> Any:
    if table is None or table.empty:
        return None
    if "Период" in table.columns:
        totals = table[table["Период"].astype(str).eq("ИТОГО")]
        if not totals.empty:
            return totals.iloc[-1]
    return table.iloc[-1]


def build_report_data(
    *,
    source_data: pd.DataFrame | None,
    rh_data: pd.DataFrame,
    periods_df: pd.DataFrame,
    boundary_table: pd.DataFrame | None,
    delta_table: pd.DataFrame | None,
    vna_results: list[pd.DataFrame] | None,
    economics_result: dict[str, Any],
    nominal_hours: dict[str, Any],
    gas_tariff: float,
    electricity_tariff: float,
    electricity_cost: float,
    source_file: str | Path | None = None,
) -> dict[str, Any]:
    """Собирает JSON-контекст после финального выбора периодов."""

    periods: list[dict[str, Any]] = []
    vna_results = vna_results or []
    vna_by_period = {}
    for position, table in enumerate(vna_results, start=1):
        period_number = table.attrs.get("period_number", position)
        try:
            period_number = int(period_number)
        except (TypeError, ValueError):
            period_number = position
        vna_by_period[period_number] = table
    for index, period_row in enumerate(periods_df.itertuples(index=False), start=1):
        start = _find_boundary(boundary_table, index, "нач")
        end = _find_boundary(boundary_table, index, "кон")
        delta = None
        if delta_table is not None and not delta_table.empty:
            matches = delta_table[delta_table["Период"].astype(str).eq(str(index))]
            if not matches.empty:
                delta = matches.iloc[0]

        periods.append({
            "number": index,
            "ordinal_genitive": ORDINAL_GENITIVE.get(index, f"{index}-го"),
            "ordinal_prepositional": ORDINAL_PREPOSITIONAL.get(index, f"{index}-м"),
            "in_period": PERIOD_INTRO.get(index, f"В {index}-м"),
            "degradation_period": DEGRADATION_PERIOD.get(index, f"в {index}-м"),
            "date_start": _date_value(getattr(period_row, "date_start", None)),
            "date_end": _date_value(getattr(period_row, "date_end", None)),
            "boundary": {
                "start": _boundary_context(start),
                "end": _boundary_context(end),
            },
            "deltas": _delta_context(delta),
            "vna_top1": _vna_top_context(
                vna_by_period.get(index)
            ),
        })

    input_total = _last_numeric(source_data, "hours_input")
    if input_total is None:
        input_total = _last_numeric(rh_data, "hours_input")
    calculated_total = _last_numeric(rh_data, "hours")
    total_row = _economics_total(economics_result.get("table"))
    annualized = economics_result.get("annualized") or {}
    weighted = (
        delta_table.attrs.get("weighted_summary") if delta_table is not None else None
    ) or {}
    vna_threshold = economics_result.get("vna_threshold")
    power_threshold = nominal_hours.get("power_threshold")
    if power_threshold is None:
        power_threshold = economics_result.get("power_threshold")

    return {
        "schema_version": "1.1",
        "source": {
            "file_name": Path(source_file).name if source_file else "",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "period_count": len(periods),
        "tariffs": {
            "gas_rub_per_1000_nm3": _number(gas_tariff, 3),
            "electricity_rub_per_mwh": _number(electricity_tariff, 2),
            "electricity_cost_rub_per_mwh": _number(electricity_cost, 2),
        },
        "summary": {
            "total_operating_hours": _number(input_total, 1),
            "calculated_total_hours": _number(calculated_total, 1),
            "nominal_power_hours": _number(nominal_hours.get("power_hours"), 1),
            "nominal_power_records": int(nominal_hours.get("power_records", 0)),
            "nominal_vna_hours": _number(nominal_hours.get("vna_hours"), 1),
            "nominal_vna_records": int(nominal_hours.get("vna_records", 0)),
        },
        "periods": periods,
        "economics": {
            "power_threshold_mw": _number(power_threshold, 1),
            "vna_threshold_percent": _number(vna_threshold, 1),
            "vna_nominal_threshold_percent": _number(NOMINAL_VNA_PERCENT, 0),
            "total": {
                "underproduction_mwh": _number(_get(total_row, "Недовыработка, МВт·ч"), 3),
                "underproduction_rub": _money(_get(total_row, "Недовыработка, руб")),
                "fuel_overrun_nm3": _number(_get(total_row, "Перерасход, нм³"), 3),
                "fuel_overrun_rub": _money(_get(total_row, "Перерасход, руб")),
                "total_cost_rub": _money(_get(total_row, "Общие издержки, руб")),
            },
            "annualized": {
                "fuel_overrun_nm3": _number(annualized.get("fuel_overrun_nm3"), 3),
                "fuel_overrun_rub": _money(annualized.get("fuel_overrun_rub")),
                "underproduction_mwh": _number(annualized.get("underproduction_mwh"), 3),
                "underproduction_rub": _money(annualized.get("underproduction_rub")),
            },
        },
        "weighted_deltas": {
            "n_priv": _number(weighted.get("delta_n"), 3),
            "n_priv_percent": _fixed_number(weighted.get("delta_n_percent")),
            "b_priv": _number(weighted.get("delta_b"), 3),
            "b_priv_percent": _fixed_number(weighted.get("delta_b_percent")),
            "eta_gtu_pp": _number(weighted.get("delta_eta"), 3),
            "eta_gtu_percent": _number(weighted.get("delta_eta_percent"), 3),
        },
    }


def save_report_data(
    report_data: dict[str, Any],
    json_path: str | Path = DEFAULT_DATA_FILE,
) -> Path:
    """Перезаписывает единый JSON последнего завершённого расчёта."""

    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(report_data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return path


def load_report_data(json_path: str | Path) -> dict[str, Any]:
    """Загружает JSON-снимок расчёта."""

    path = Path(json_path)
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("Корень JSON с данными отчёта должен быть объектом.")
    periods = data.get("periods", [])
    if not isinstance(periods, list):
        raise ValueError("Поле periods в JSON должно быть массивом.")
    for period in periods:
        if isinstance(period, dict) and "ordinal_prepositional" not in period:
            try:
                number = int(period.get("number"))
            except (TypeError, ValueError):
                continue
            period["ordinal_prepositional"] = ORDINAL_PREPOSITIONAL.get(
                number, f"{number}-м"
            )
        if isinstance(period, dict) and "in_period" not in period:
            try:
                number = int(period.get("number"))
            except (TypeError, ValueError):
                continue
            period["in_period"] = PERIOD_INTRO.get(number, f"В {number}-м")
        if isinstance(period, dict) and "degradation_period" not in period:
            try:
                number = int(period.get("number"))
            except (TypeError, ValueError):
                continue
            period["degradation_period"] = DEGRADATION_PERIOD.get(
                number, f"в {number}-м"
            )
    data["periods"] = PeriodCollection(periods)
    return data


def list_templates(template_dir: str | Path = DEFAULT_TEMPLATE_DIR) -> list[Path]:
    """Возвращает DOCX-шаблоны для будущего списка шаблонов."""

    directory = Path(template_dir)
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.docx") if path.is_file())


def generate_report(
    report_data: dict[str, Any],
    template_path: str | Path = DEFAULT_TEMPLATE,
    output_path: str | Path = DEFAULT_REPORT_DIR / "report.docx",
) -> Path:
    """Рендерит DOCX-шаблон и возвращает путь к результату."""

    template = Path(template_path)
    output = Path(output_path)
    if not template.is_file():
        raise FileNotFoundError(f"Шаблон Word не найден: {template}")
    output.parent.mkdir(parents=True, exist_ok=True)

    document = DocxTemplate(str(template))
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    context = dict(report_data)
    # Дата относится к моменту формирования Word, а не к запуску расчёта.
    context["current_date"] = datetime.now().strftime("%d.%m.%Y")
    periods = context.get("periods", [])
    if isinstance(periods, list) and not isinstance(periods, PeriodCollection):
        context["periods"] = PeriodCollection(periods)
    for period in context["periods"]:
        deltas = period.get("deltas", {})
        if "show_no_degradation_text" not in deltas:
            values = (deltas.get("n_priv"), deltas.get("b_priv"))
            deltas["show_no_degradation_text"] = any(
                str(value).strip() in {"0", "0,0", "0,00", "0,000"}
                for value in values
            )
    document.render(context, jinja_env=environment)
    document.save(str(output))
    return output


def generate_report_from_json(
    json_path: str | Path,
    template_path: str | Path = DEFAULT_TEMPLATE,
    output_path: str | Path = DEFAULT_REPORT_DIR / "report.docx",
) -> Path:
    """Загружает JSON и формирует DOCX одним вызовом."""

    return generate_report(load_report_data(json_path), template_path, output_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Сформировать Word-отчёт из JSON-снимка расчёта."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_DIR / "report.docx")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = generate_report_from_json(args.data, args.template, args.output)
    print(f"Word-отчёт создан: {result.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
