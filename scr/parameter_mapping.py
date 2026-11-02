"""Explicit parameter names and pressure units; no tag-name similarity matching."""
import re
from unit_conversions import PRESSURE_UNITS, unit_factor, unit_info, canonical_unit, UNIT_CATALOG

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


def header_unit(header):
    parts = str(header or "").replace("\n", " ").split(",", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def parameter_for_header(header, station_id=None):
    text = re.sub(r"\s+", "", str(header or "").split(",", 1)[0].casefold())
    if text in {"pнк", "рнк"} and station_id == "syz_tec":
        return "inlet_pressure_drop"
    if text == "n":
        unit = unit_info(header_unit(header))
        if unit and unit['dimension'] == 'power':
            return "power"
        if unit and unit['dimension'] == 'rotation':
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
