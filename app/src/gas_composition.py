"""C/H mass ratio of combustible components from molar fractions, not Excel positions.

Formulas: NIST https://wtt-lite.nist.gov/wtt-lite/help/lite.html
Atomic masses: CIAAW https://ciaaw.org/abridged-atomic-weights.htm
"""
import math

CH_METHOD = 'combustible_mass_v1'
CARBON_MASS, HYDROGEN_MASS = 12.011, 1.008  # g/mol, CIAAW abridged 2024
_SPECIES = (
    ('Methane','CH4',1,4,True), ('Ethane','C2H6',2,6,True),
    ('n-Propane','C3H8',3,8,True), ('IsoButane','C4H10',4,10,True),
    ('n-Butane','C4H10',4,10,True), ('n-Pentane','C5H12',5,12,True),
    ('Isopentane','C5H12',5,12,True), ('n-Hexane','C6H14',6,14,True),
    ('n-Heptane','C7H16',7,16,True), ('CarbonDioxide','CO2',1,0,False),
    ('Nitrogen','N2',0,0,False), ('Oxygen','O2',0,0,False),
    ('Helium','He',0,0,False), ('Hydrogen','H2',0,2,True),
    ('Argon','Ar',0,0,False), ('Water','H2O',0,2,False),
    ('CarbonMonoxide','CO',1,0,True), ('HydrogenSulfide','H2S',0,2,True),
)
SPECIES = {name.casefold():dict(formula=formula,carbon=c,hydrogen=h,combustible=fuel)
           for name,formula,c,h,fuel in _SPECIES}


def ch_model():
    return dict(method=CH_METHOD,carbon_mass=CARBON_MASS,hydrogen_mass=HYDROGEN_MASS,species=SPECIES)


def calculate_ch(components):
    """Fractions are used as supplied; missing components are not inferred or normalized."""
    rows=components.items() if isinstance(components,dict) else components
    carbon=hydrogen=0.
    seen=set()
    for name,value in rows:
        key=str(name).strip().casefold()
        if key in seen:raise ValueError(f'Повторный компонент: {name}.')
        seen.add(key)
        try:value=float(str(value).strip().replace(',','.'))
        except (ValueError,TypeError) as error:raise ValueError(f'{name}: введите молярную долю.') from error
        if not math.isfinite(value) or not 0<=value<=1:
            raise ValueError(f'Доля {name} должна быть от 0 до 1.')
        if value==0:continue
        species=SPECIES.get(key)
        if species is None:
            raise ValueError(f'Для компонента {name} неизвестна химическая формула. C/H не рассчитано.')
        if species['combustible']:
            carbon+=value*species['carbon'];hydrogen+=value*species['hydrogen']
    if hydrogen<=0:
        raise ValueError('Для C/H укажите молярные доли горючих компонентов с водородом: углеводороды или H₂.')
    return CARBON_MASS*carbon/(HYDROGEN_MASS*hydrogen)
