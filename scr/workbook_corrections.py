"""Semantic names for correction columns; formulas remain owned by the book."""
import re


_FACTORS = (
    ('temperature', 'температуры', ('t',)),
    ('atmospheric_pressure', 'атмосферного давления', ('p',)),
    ('humidity', 'влажности', ('φ', 'ф', 'ϕ')),
    ('inlet_loss', 'потерь давления на входе', ('δpвх', 'δpнк')),
    ('outlet_loss', 'давления уходящих газов', ('δpвых',)),
    ('fuel_temperature', 'температуры топлива', ('tг', 'тг')),
    ('fuel_properties', 'свойств топлива', ('c/h', 'с/н')),
    ('speed', 'частоты вращения', ('n', 'n/n0')),
)
CORRECTION_ROLES = {
    f'correction_{key}_{result}': (f'Поправка {label} на {target}', 'о.е.')
    for key, label, _ in _FACTORS
    for result, target in (('power', 'мощность'), ('efficiency', 'КПД'))
}


def correction_role(header):
    # Normalize typography, not meanings: ambiguous labels stay unassigned.
    text = str(header or '').split(',', 1)[0].casefold()
    text = text.translate(str.maketrans({'ₙ':'n', 'ₜ':'t', 'ₚ':'p', '₀':'0', 'р':'p', 'т':'t', 'к':'k', 'н':'n'}))
    text = re.sub(r'[\s_{}()\[\]]', '', text)
    for key, _, symbols in _FACTORS:
        for symbol in symbols:
            symbol = symbol.translate(str.maketrans({'р':'p', 'т':'t', 'к':'k', 'н':'n'}))
            for suffix, result in (('n','power'), ('η','efficiency')):
                if text == 'k' + symbol + suffix:
                    return f'correction_{key}_{result}'
    return ''
