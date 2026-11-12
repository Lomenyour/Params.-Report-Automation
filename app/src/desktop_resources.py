"""Пути к локальным ресурсам обеих стадий десктопного интерфейса."""
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "desktop_ui"
APP_ICON = UI_DIR / "app-icon.ico"
STARTUP_PLANT = UI_DIR / "startup-plant.png"
