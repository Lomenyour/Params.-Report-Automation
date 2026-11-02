"""Confirmed mappings per station/unit and order-independent source signature."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from json_store import read_json, write_json, transaction


def signature(headers):
    tags = sorted(str(tag).strip().casefold() for tag in headers if str(tag).casefold() not in {"date", "time", "milliseconds"})
    return hashlib.sha256(json.dumps(tags, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_store(path):
    path = Path(path)
    legacy = path.with_name("sensor_mappings.json")
    source = path if path.exists() or not legacy.exists() else legacy
    data = read_json(source, {"schema_version": 2, "profiles": {}})
    if "schema_version" not in data:
        return {"schema_version": 2, "profiles": {}, "legacy": data}
    if data.get("schema_version") != 2 or not isinstance(data.get("profiles"), dict):
        raise ValueError("Неподдерживаемый справочник маппинга. Исходный JSON не изменён.")
    return data


def load_mapping(path, station, unit, headers, *, store=None):
    data = store if store is not None else load_store(path)
    owner = data["profiles"].get(f"{station}|{unit}")
    if not owner or not owner.get("sets"):
        return None
    if not isinstance(owner["sets"], list) or any(not isinstance(item, dict) or
            not isinstance(item.get("signature"), str) or not isinstance(item.get("mappings"), list)
            for item in owner["sets"]):
        raise ValueError("Повреждён профиль маппинга; исходный JSON не изменён.")
    selected = next((item for item in reversed(owner["sets"]) if item["signature"] == signature(headers)), None)
    selected = selected or owner["sets"][-1]
    return selected["mappings"]


def save_mapping(path, station, unit, headers, mappings):
    with transaction():
        data = load_store(path)
        key = f"{station}|{unit}"
        owner = data["profiles"].setdefault(key, {"sets": [], "history": []})
        sig = signature(headers)
        record = {"signature": sig, "tags": list(headers), "mappings": mappings,
                  "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        previous = next((item for item in owner["sets"] if item["signature"] == sig), None)
        if previous:
            owner["history"].append(previous)
        owner["sets"] = [item for item in owner["sets"] if item["signature"] != sig] + [record]
        write_json(path, data)
