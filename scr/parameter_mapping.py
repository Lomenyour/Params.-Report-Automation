"""Explicit parameter names and pressure units; no tag-name similarity matching."""
import re

PARAMETERS = {
    "ambient_temperature": ("Температура наружного воздуха", ("токр", "tокр", "токр.воздуха")),
    "relative_humidity": ("Относительная влажность", ("ф", "φ", "ϕ")),
    "atmospheric_pressure": ("Атмосферное давление", ("pатм", "ратм", "pатм.")),
    "vlo": ("Перепад ВЛО", ("вло",)), "fgo": ("Перепад ФГО", ("фго",)),
    "fto": ("Перепад ФТО", ("фто",)), "fgo_fto": ("Перепад ФГО+ФТО", ("фго+фто",)),
    "inlet_pressure_drop": ("Потеря давления на входе", ("δpнк", "δрнк", "δpвх")),
    "inlet_pressure": ("Абсолютное давление перед компрессором", ("pнк", "рнк")),
    "inlet_temperature": ("Температура перед компрессором", ("тнк", "tнк")),
    "outlet_pressure": ("Давление за компрессором", ("pкк", "ркк")),
    "outlet_temperature": ("Температура за компрессором", ("ткк", "tкк")),
    "vna": ("Положение ВНА", ("вна",)), "fuel_flow": ("Расход топливного газа", ("b", "в")),
    "fuel_pressure": ("Давление топливного газа", ("pгаза", "pгаз", "ргаза", "ргаз")),
    "fuel_temperature": ("Температура топливного газа", ("tгаза", "тгаза", "tгаз", "тгаз")),
    "exhaust_temperature": ("Температура уходящих газов", ("татк", "tатк")),
    "power": ("Фактическая мощность", ("n",)), "rpm": ("Частота вращения", ("n",)),
    "power_factor": ("Коэффициент мощности", ("cosφ", "cos(φ)")),
    "exhaust_pressure": ("Давление уходящих газов", ("давление ух.газов", "давлениеух.газов")),
}
PRESSURE_UNITS = {"па": 1., "pa": 1., "кпа": 1000., "kpa": 1000., "мпа": 1e6,
                  "mpa": 1e6, "бар": 1e5, "bar": 1e5, "barabs": 1e5,
                  "мбар": 100., "mbar": 100., "hpa": 100., "гпа": 100.,
                  "мм рт. ст.": 133.322368, "ммрт.ст.": 133.322368,
                  "мм вод. ст.": 9.80665, "ммвод.ст.": 9.80665}


def header_unit(header):
    parts = str(header or "").replace("\n", " ").split(",", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def unit_factor(source, target):
    def clean(unit): return re.sub(r"\s+", " ", unit.strip().casefold())
    source, target = clean(source), clean(target)
    if not source or not target or source == target:
        return 1.
    if source in PRESSURE_UNITS and target in PRESSURE_UNITS:
        return PRESSURE_UNITS[source] / PRESSURE_UNITS[target]
    raise ValueError(f"Неизвестное преобразование единиц: {source} → {target}. Укажите коэффициент явно.")


def parameter_for_header(header, station_id=None):
    text = re.sub(r"\s+", "", str(header or "").split(",", 1)[0].casefold())
    if text in {"pнк", "рнк"} and station_id == "syz_tec":
        return "inlet_pressure_drop"
    if text == "n":
        unit = header_unit(header).casefold()
        if unit in {"мвт", "mw", "квт", "kw"}:
            return "power"
        if unit in {"об/мин", "об./мин", "rpm", "мин-1", "мин⁻¹", "гц", "hz", "с-1", "с⁻¹"}:
            return "rpm"
        return ""  # N без единиц неоднозначно: мощность или частота вращения.
    for key, (_, aliases) in PARAMETERS.items():
        if text in [re.sub(r"\s+", "", alias) for alias in aliases]:
            return key
    return ""


def parameter_targets(headers, station_id=None):
    result = {}
    for column, header in headers.items():
        parameter = parameter_for_header(header, station_id)
        if parameter:
            result.setdefault(parameter, []).append(column)
    return {parameter: columns[0] for parameter, columns in result.items() if len(columns) == 1}
