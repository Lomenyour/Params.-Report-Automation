"""Экспорт утверждённого белого знака в прозрачный Windows ICO.

PNG белого знака на чёрном остаётся неизменным. Для Windows цвет знака
белый, а его яркость используется как покрытие прозрачной иконки, как
при screen-смешении в HTML. Это экспорт монохромного значка, не новый рисунок.
"""
from pathlib import Path

from PIL import Image

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def export_icon(source, destination):
    with Image.open(source) as approved:
        coverage = approved.convert("L")
        # Убираем только почти чёрный шум фона; сохраняем сглаживание контура.
        coverage = coverage.point(lambda value: round(max(0, min(255, (value - 8) * 255 / 239))))
        icon = Image.new("RGBA", approved.size, "white")
        icon.putalpha(coverage)
        icon.save(destination, format="ICO", sizes=[(size, size) for size in ICON_SIZES])


if __name__ == "__main__":
    resources = Path(__file__).resolve().parents[1] / "scr/desktop_ui"
    export_icon(resources / "app-icon.png", resources / "app-icon.ico")
