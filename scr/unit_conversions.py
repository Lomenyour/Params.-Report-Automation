"""Shared affine conversions; base = value * factor + offset.

Temperatures are absolute temperatures. Normal and actual gas volumes remain
different dimensions; an offset is never guessed for unlabelled data.
"""
import re


# symbol, dimension, multiplier to the dimension's base unit, accepted aliases
_ROWS = (
    ('Па','pressure',1.,('pa',)), ('кПа','pressure',1000.,('kpa',)),
    ('МПа','pressure',1e6,('mpa',)), ('бар','pressure',1e5,('bar','barabs')),
    ('мбар','pressure',100.,('mbar',)), ('гПа','pressure',100.,('hpa',)),
    ('мм вод. ст.','pressure',9.80665,('ммвод.ст.','мм вод ст','mmh2o','мм водяного столба')),
    ('мм рт. ст.','pressure',133.322368,('ммрт.ст.','мм рт ст','mmhg','мм ртутного столба')),
    ('дюйм вод. ст. (условн.)','pressure',249.08891,('дюйм вод. ст.','дюйм вод ст','дюйм водяного столба',
        'inh2o','inh₂o','in.h2o','in.w.c.','inwc','in.wg','inwg','"h2o','"h₂o')),
    ('дюйм вод. ст. (4 °C)','pressure',249.082,('inh2o(4°c)','inh₂o(4°c)','inh2o@4c','inh2o@4°c','inh2o(39.2°f)','inh2o@39.2f','inh2o@39.2°f')),
    ('дюйм вод. ст. (60 °F)','pressure',248.84,('inh2o(60°f)','inh₂o(60°f)','inh2o@60f','inh2o@60°f')),
    ('дюйм рт. ст. (условн.)','pressure',3386.389,('дюйм рт. ст.','дюйм рт ст','дюйм ртутного столба','inhg','in.hg','"hg')),
    ('м³/с','volume_flow',1.,('м3/с','m3/s','m³/s')),
    ('м³/ч','volume_flow',1/3600,('м3/ч','m3/h','m³/h')),
    ('л/с','volume_flow',.001,('l/s',)), ('л/мин','volume_flow',.001/60,('l/min',)),
    ('л/ч','volume_flow',.001/3600,('l/h',)),
    ('нм³/с','normal_volume_flow',1.,('нм3/с','nm3/s','nm³/s')),
    ('нм³/ч','normal_volume_flow',1/3600,('нм3/ч','nm3/h','nm³/h')),
    ('тыс. нм³/ч','normal_volume_flow',1000/3600,('тыс.нм3/ч','тыс. нм3/ч')),
    ('кг/с','mass_flow',1.,('kg/s','кг/сек')),
    ('кг/ч','mass_flow',1/3600,('kg/h',)), ('т/ч','mass_flow',1000/3600,('t/h',)),
    ('Гц','rotation',1.,('hz','об/с','1/с','с-1','с⁻¹')),
    ('об/мин','rotation',1/60,('rpm','об./мин','мин-1','мин⁻¹')),
    ('тыс. об/мин','rotation',1000/60,('т.об/мин','тыс.об/мин')),
    ('Вт','power',1.,('w',)), ('кВт','power',1000.,('kw',)), ('МВт','power',1e6,('mw',)),
    ('о.е.','fraction',1.,('о.е','о. е.','доля','доли','1','безразмерная','-')),
    ('%','fraction',.01,()),
    ('°C','temperature',1.,('°с','° c','° с','c','с','град.с','degc','celsius')),
    ('K','temperature',1.,('к','кельвин','°k','kelvin')),
    ('°F','temperature',5/9,('°f','f','degf','fahrenheit')),
)


def _key(value):
    return re.sub(r'\s+', '', str(value or '').casefold())


_OFFSETS={'°C':273.15,'K':0.,'°F':273.15-32*5/9}
UNIT_CATALOG = tuple(dict(symbol=symbol, dimension=dimension, factor=factor,offset=_OFFSETS.get(symbol,0.),
                         aliases=list(dict.fromkeys((_key(symbol), *(_key(a) for a in aliases)))))
                     for symbol, dimension, factor, aliases in _ROWS)
_LOOKUP = {alias: row for row in UNIT_CATALOG for alias in row['aliases']}
PRESSURE_UNITS = {alias: row['factor'] for alias, row in _LOOKUP.items() if row['dimension']=='pressure'}
PRESSURE_UNITS.update({alias.casefold(): factor for symbol, dimension, factor, aliases in _ROWS
                       if dimension=='pressure' for alias in (symbol, *aliases)})


def unit_info(value):
    return _LOOKUP.get(_key(value))


def canonical_unit(value):
    row = unit_info(value)
    return row['symbol'] if row else str(value or '').strip()


# A suffix must be a whole printed unit: do not reduce нм³/ч to м³/ч,
# or an unknown т.1об/мин to об/мин. Bare digits/letters are ambiguous in descriptions.
_SUFFIXES = tuple((re.compile(r'(?<![\w.])' + r'\s*'.join(re.escape(ch) for ch in alias) + r'\s*$', re.I), row['symbol'])
                  for alias, row in sorted(_LOOKUP.items(), key=lambda item: len(item[0]), reverse=True)
                  if len(alias) > 1 or alias in {'%', '°'})


def extract_unit(description):
    text = str(description)
    # One-letter temperature units are unambiguous only in an explicit unit field.
    explicit = re.search(r'(?:^|[,;\[(])\s*([KКCF])\s*[\])]?$' , text, re.I)
    if explicit:
        return canonical_unit(explicit[1])
    return next((symbol for pattern, symbol in _SUFFIXES if pattern.search(text)), '')


def unit_conversion(source, target):
    """Return (multiplier, additive offset) for one compatible unit pair."""
    if not source or not target or _key(source)==_key(target):
        return 1.,0.
    left, right = unit_info(source), unit_info(target)
    if left and right and left['dimension']==right['dimension']:
        return left['factor']/right['factor'],(left['offset']-right['offset'])/right['factor']
    raise ValueError(f'Несовместимые или неизвестные единицы: {source} → {target}. Проверьте назначение и единицы.')


def convert_units(values,source,target):
    multiplier,offset=unit_conversion(source,target)
    return values*multiplier+offset


def unit_factor(source,target):
    """Compatibility API for paths that can only apply a pure multiplier."""
    multiplier,offset=unit_conversion(source,target)
    if offset!=0:
        raise ValueError('Перевод температур требует смещения; используйте полное преобразование единиц.')
    return multiplier
