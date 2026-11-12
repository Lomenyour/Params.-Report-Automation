"""Strict local JSON writes: validate before mutation, keep a recoverable previous copy."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

_lock = RLock()


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Ожидается объект JSON")
        return value
    except (OSError, ValueError) as error:
        raise ValueError(f"Не удалось прочитать {path}. Файл сохранён без изменений.") from error


def _replace_bytes(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, data):
    path = Path(path)
    encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _replace_bytes(path.with_suffix(path.suffix + ".bak"), path.read_bytes())
    _replace_bytes(path, encoded)


@contextmanager
def transaction():
    with _lock:
        yield
