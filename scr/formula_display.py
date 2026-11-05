"""Read-only notation for the same parameter-based AST the evaluator executes.

No Excel text substitutions, algebraic simplification or recursive expansion
of dependencies. Presentation names never become calculation identifiers.
"""
from collections import Counter
import json
import math

PARAMETER_SYMBOLS = {
    'date':'Дата', 'hours_input':'Наработка',
    'ambient_temperature':'Tокр', 'relative_humidity':'φокр',
    'p_atm_pa':'Pатм', 'p_nk_pa':'Pнк', 'inlet_pressure_drop':'ΔPвх',
    't':'Tнк', 'tkk':'Tкк', 'p_kk_mpa':'Pкк', 'vna':'ВНА', 'rpm':'n',
    'power_n':'Nизм', 'fuel_flow':'Bизм', 'power':'Nприв', 'fuel':'Bприв',
    'fuel_specific':'bприв', 'eta_compressor':'ηк', 'pi_k':'πк',
    'gas_pressure':'Pгаз', 'gas_temperature':'Tгаз', 'q_lower':'Qнр_об',
    'gas_q_mass':'Qнр_масс', 'gas_density':'ρгаз', 'gas_c_h':'(C/H)',
    'power_factor':'cosφ', 'vlo':'ΔPВЛО', 'fgo':'ΔPФГО', 'fto':'ΔPФТО',
    'fgo_fto':'ΔP(ФГО+ФТО)', 'exhaust_pressure':'Pух', 'exhaust_temperature':'Tух',
}
for key, symbol in (
    ('temperature','T'), ('atmospheric_pressure','P'), ('humidity','φ'),
    ('inlet_loss','ΔPвх'), ('outlet_loss','ΔPвых'),
    ('fuel_temperature','tг'), ('fuel_properties','(C/H)'), ('speed','(n/n0)'),
):
    for result, suffix in (('power','N'),('efficiency','η')):
        PARAMETER_SYMBOLS[f'correction_{key}_{result}']='k'+symbol+suffix

_PRECEDENCE={'=':10,'<>':10,'<':10,'>':10,'<=':10,'>=':10,
             '+':20,'-':20,'*':30,'/':30,'^':60}
_OPERATORS={'*':'×','-':'−','<>':'≠','<=':'≤','>=':'≥'}
_FUNCTIONS={'IF':'ЕСЛИ','IFERROR':'ЕСЛИОШИБКА','SUM':'СУММА',
            'AVERAGE':'СРЕДНЕЕ','AND':'И','OR':'ИЛИ',
            'PROPSSI':'CoolProp.PropsSI','HAPROPSSI':'CoolProp.HAPropsSI'}
_SUBSCRIPTS=str.maketrans('0123456789','₀₁₂₃₄₅₆₇₈₉')


def parameter_symbols(columns, column_ids):
    names={}; unnamed=0
    for row in columns:
        header=str(row['header'] or '').split(',',1)[0].strip()
        if row['role'] in PARAMETER_SYMBOLS: name=PARAMETER_SYMBOLS[row['role']]
        elif header: name='«'+header+'»' if any(char.isspace() or char in '+-*/^=<>;' for char in header) else header
        else:
            unnamed+=1;name='вспом_'+str(unnamed)
        names[column_ids[row['column']]]=name
    counts=Counter(names.values());seen=Counter()
    for identifier,name in list(names.items()):
        if counts[name]>1:
            seen[name]+=1;names[identifier]=name+'_'+str(seen[name])
    return names


class FormulaNotation:
    """One equation's local coefficient symbols and referenced parameter IDs."""
    def __init__(self, symbols):
        self.symbols=symbols;self.coefficients={};self.dependencies=[]

    def render(self,node):
        return self._render(node)[0]

    def _render(self,node):
        kind=node[0]
        if kind=='number':
            value=float(node[1])
            if not math.isfinite(value): raise ValueError('Нефинитная числовая константа')
            text=str(int(value)) if value.is_integer() and abs(value)<1e15 else repr(value)
            return text,100 if value>=0 else 50
        if kind=='text':return json.dumps(node[1],ensure_ascii=False),100
        if kind=='data':
            identifier,offset=node[1:]
            if identifier not in self.symbols: raise ValueError('Не определён параметр '+identifier)
            if (identifier,offset) not in self.dependencies:self.dependencies.append((identifier,offset))
            suffix='' if offset==0 else f'[t{"+" if offset>0 else "−"}{abs(offset)}]'
            return self.symbols[identifier]+suffix,100
        if kind=='constant':
            if node[1]!='coefficients': raise ValueError('Ожидался идентификатор коэффициента')
            identifier=node[2]
            if identifier not in self.coefficients:
                self.coefficients[identifier]='c'+str(len(self.coefficients)+1).translate(_SUBSCRIPTS)
            return self.coefficients[identifier],100
        if kind=='unary':
            child,precedence=self._render(node[2])
            if precedence<50:child='('+child+')'
            return _OPERATORS.get(node[1],node[1])+child,50
        if kind=='binary':
            operator=node[1];precedence=_PRECEDENCE[operator]
            left,lp=self._render(node[2]);right,rp=self._render(node[3])
            if lp<precedence or (lp==precedence and (operator=='^' or precedence==10)):left='('+left+')'
            if rp<=precedence:right='('+right+')'
            if operator=='^' and node[3][0]=='number' and node[3][1] in (2,3):
                return left+('²' if node[3][1]==2 else '³'),precedence
            return f'{left} {_OPERATORS.get(operator,operator)} {right}',precedence
        if kind=='range':return '; '.join(self._render(child)[0] for child in node[1]),100
        if kind=='call':
            name=_FUNCTIONS.get(node[1],node[1])
            return name+'('+('; '.join(self._render(child)[0] for child in node[2]))+')',100
        raise ValueError('Не поддерживается отображение узла '+str(kind))
