"""Ручные события для диаграммы; отдельный локальный профиль станции и ГТ."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile


@dataclass(frozen=True)
class ChartEvent:
    date: datetime
    label: str


def parse_chart_events(text: str) -> tuple[ChartEvent, ...]:
    if not isinstance(text, str):
        raise ValueError("Некорректный формат списка событий.")
    events = []
    formats = ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d-%m-%Y %H:%M", "%d-%m-%Y")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        date_text, separator, label = line.partition(";")
        if not separator or not label.strip():
            raise ValueError(f"Строка {number}: укажите дату и подпись через точку с запятой.")
        date = None
        for pattern in formats:
            try:
                date = datetime.strptime(date_text.strip(), pattern)
                break
            except ValueError:
                pass
        if date is None:
            raise ValueError(f"Строка {number}: дата должна иметь вид дд.мм.гггг или дд.мм.гггг чч:мм.")
        event = ChartEvent(date, label.strip())
        if event not in events:
            events.append(event)
    return tuple(sorted(events, key=lambda event: event.date))


def format_chart_events(events: tuple[ChartEvent, ...]) -> str:
    return "\n".join(f"{event.date:%d.%m.%Y %H:%M}; {event.label}" for event in events)


def _events_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
    return base / "GTU_Report" / "chart_events.json"


def _key(book_path: str | Path) -> str:
    match = re.search(
        r"^(.*?)[\s_-]+(?:ГТ|GT)[-\s_]*(\d+)(?=$|[^0-9])",
        Path(book_path).stem, re.I,
    )
    if match:
        station = re.sub(r"[\s_]+", " ", match.group(1).strip()).casefold()
        return f"{station}|{match.group(2)}"
    return "file:" + str(Path(book_path).resolve()).casefold()


def load_chart_events(book_path: str | Path) -> tuple[ChartEvent, ...]:
    path = _events_path()
    if not path.exists():
        return ()
    profiles = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profiles, dict):
        raise ValueError("Некорректный формат профилей событий.")
    return parse_chart_events(profiles.get(_key(book_path), ""))


def save_chart_events(book_path: str | Path, events: tuple[ChartEvent, ...]) -> None:
    path = _events_path()
    profiles = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(profiles, dict):
        raise ValueError("Некорректный формат профилей событий.")
    profiles[_key(book_path)] = format_chart_events(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".chart_events_", suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(profiles, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
