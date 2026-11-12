"""Verified exact tag-set variants. Reference-only entries cannot auto-map data."""
from pathlib import Path
import json
import sys
from functools import lru_cache


def variants_path():
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).parent / "config/source_variants.json"
        if external.exists():
            return external
        return Path(sys._MEIPASS) / "config/source_variants.json"
    return Path(__file__).resolve().parents[1] / "config/source_variants.json"


@lru_cache(maxsize=2)
def _read_catalog(path, modified, size):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("variants"), list):
        raise ValueError("Неверный справочник вариантов датчиков.")
    return data


def catalog():
    path = variants_path()
    if not path.exists():
        return {"variants": []}
    stat = path.stat()
    return _read_catalog(str(path), stat.st_mtime_ns, stat.st_size)


def deferred_channels(station_id, unit):
    return {row["tag"].casefold() for row in catalog().get("deferred_channels", [])
            if row["station_id"] == station_id and row["unit"] == unit}


def match_variant(headers, company_id):
    data = catalog()
    tags = [str(tag).strip().casefold() for tag in headers if str(tag).casefold() not in {"date", "time", "milliseconds"}]
    if len(tags) != len(set(tags)):
        raise ValueError("Повторные теги нельзя сопоставить с вариантом.")
    matches = []
    for variant in data["variants"]:
        if not variant.get("enabled") or variant["company_id"] != company_id:
            continue
        assignments = variant["assignments"]
        expected = [row["tag"].casefold() for row in assignments]
        parameters = [row["parameter"] for row in assignments]
        if len(set(expected)) != len(expected) or len(set(parameters)) != len(parameters):
            raise ValueError(f"Неоднозначные назначения в варианте {variant['id']}.")
        if set(tags) == set(expected):
            matches.append(variant)
    return matches[0] if len(matches) == 1 else None
