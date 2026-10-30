"""Экспорт крыльчатки утверждённого белого знака в прозрачный Windows ICO.

PNG белого знака на чёрном остаётся неизменным. Для Windows цвет знака
белый, а его яркость используется как покрытие прозрачной иконки, как
при screen-смешении в HTML. Это экспорт монохромного значка, не новый рисунок.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
ICON_PADDING = .02
ROTOR_CENTER = .498
ROTOR_RADIUS = .305


def export_icon(source, destination):
    with Image.open(source) as approved:
        coverage = approved.convert("L")
        # Убираем только почти чёрный шум фона; сохраняем сглаживание контура.
        coverage = coverage.point(lambda value: round(max(0, min(255, (value - 8) * 255 / 239))))
        # Круглый фрагмент из согласованного макета: крупная крыльчатка без обода.
        # Граница проходит в пустом зазоре между ротором и неподвижным корпусом.
        center_x, center_y = coverage.width * ROTOR_CENTER, coverage.height * ROTOR_CENTER
        radius = min(coverage.size) * ROTOR_RADIUS
        rotor = Image.new("L", coverage.size, 0)
        ImageDraw.Draw(rotor).ellipse((center_x-radius, center_y-radius,
                                      center_x+radius, center_y+radius), fill=255)
        coverage = ImageChops.multiply(coverage, rotor)
        # Убираем пустые поля исходного холста, не меняя контуры знака.
        bounds = coverage.point(lambda value: 255 if value >= 64 else 0).getbbox()
        if bounds is None:
            raise ValueError("У значка нет видимого рисунка.")
        left, top, right, bottom = bounds
        coverage = coverage.crop((max(0, left-2), max(0, top-2),
                                  min(coverage.width, right+2), min(coverage.height, bottom+2)))
        side = max(coverage.size)
        canvas_side = round(side / (1 - 2 * ICON_PADDING))
        canvas = Image.new("L", (canvas_side, canvas_side), 0)
        canvas.paste(coverage, ((canvas_side-coverage.width)//2, (canvas_side-coverage.height)//2))
        frames = []
        for size in ICON_SIZES:
            alpha = canvas.resize((size, size), Image.Resampling.LANCZOS)
            if size <= 24:
                peak = alpha.getextrema()[1]
                alpha = alpha.point(lambda value: round(value * 255 / peak))
            frame = Image.new("RGBA", (size, size), "white")
            frame.putalpha(alpha)
            frames.append(frame)
        frames[-1].save(destination, format="ICO", sizes=[(s, s) for s in ICON_SIZES],
                        append_images=frames[:-1])


if __name__ == "__main__":
    resources = Path(__file__).resolve().parents[1] / "scr/desktop_ui"
    export_icon(resources / "app-icon.png", resources / "app-icon.ico")
