"""Restricted Excel expressions compiled to data/constant references, never eval()."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

import numpy as np
import pandas as pd
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter
from CoolProp.CoolProp import PropsSI
from CoolProp.HumidAirProp import HAPropsSI

FUNCTIONS = {'IF', 'IFERROR', 'SUM', 'AVERAGE', 'AND', 'OR', 'ABS', 'MIN', 'MAX',
             'SQRT', 'POWER', 'ROUND', 'EXP', 'LN', 'LOG10', 'PROPSSI', 'HAPROPSSI'}


def node_id(node):
    return hashlib.sha256(json.dumps(node, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class FormulaParser:
    def __init__(self, formula, origin_row, data_sheet='Данные'):
        self.tokens = [t for t in Tokenizer('=' + formula.lstrip('=')).items if t.type != 'WHITE-SPACE']
        self.pos, self.row, self.sheet = 0, origin_row, data_sheet

    def parse(self):
        result = self.expression()
        if self.pos != len(self.tokens):
            raise ValueError('Не поддерживается часть выражения: ' + self.tokens[self.pos].value)
        return result

    def expression(self, minimum=0):
        if self.pos >= len(self.tokens):
            raise ValueError('Незавершённая формула')
        token = self.tokens[self.pos]
        self.pos += 1
        if token.type == 'OPERATOR-PREFIX' and token.value in ('+', '-'):
            left = ['unary', token.value, self.expression(4)]
        elif token.type == 'PAREN' and token.subtype == 'OPEN':
            left = self.expression()
            self.close('PAREN')
        elif token.type == 'FUNC' and token.subtype == 'OPEN':
            name = token.value[:-1].split('!')[-1].upper().removeprefix('_XLFN.')
            if name not in FUNCTIONS:
                raise ValueError('Не поддерживается функция ' + name)
            args = []
            if not (self.pos < len(self.tokens) and self.tokens[self.pos].type == 'FUNC' and self.tokens[self.pos].subtype == 'CLOSE'):
                while True:
                    args.append(self.expression())
                    if self.pos >= len(self.tokens) or self.tokens[self.pos].type != 'SEP':
                        break
                    self.pos += 1
            self.close('FUNC')
            arity={'IF':(2,3),'IFERROR':(2,2),'ABS':(1,1),'SQRT':(1,1),'POWER':(2,2),
                   'ROUND':(2,2),'EXP':(1,1),'LN':(1,1),'LOG10':(1,1),'PROPSSI':(6,6),'HAPROPSSI':(7,7)}
            if name in arity and not arity[name][0]<=len(args)<=arity[name][1]:
                raise ValueError('Неверное число аргументов '+name)
            if not args: raise ValueError('Нет аргументов '+name)
            left = ['call', name, args]
        elif token.type == 'OPERAND':
            if token.subtype == 'NUMBER':
                left = ['number', float(token.value)]
            elif token.subtype == 'TEXT':
                left = ['text', token.value[1:-1].replace('""', '"')]
            elif token.subtype == 'LOGICAL':
                left = ['number', float(token.value.upper() == 'TRUE')]
            elif token.subtype == 'RANGE':
                left = self.reference(token.value)
            else:
                raise ValueError('Не поддерживается операнд ' + token.value)
        else:
            raise ValueError('Не поддерживается выражение ' + token.value)
        precedence = {'=': 1, '<>': 1, '<': 1, '>': 1, '<=': 1, '>=': 1,
                      '+': 2, '-': 2, '*': 3, '/': 3, '^': 5}
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            if token.type == 'OPERATOR-POSTFIX' and token.value == '%':
                self.pos += 1
                left = ['binary', '/', left, ['number', 100.]]
                continue
            priority = precedence.get(token.value, -1) if token.type == 'OPERATOR-INFIX' else -1
            if priority < minimum:
                break
            self.pos += 1
            right = self.expression(priority + 1)
            left = ['binary', token.value, left, right]
        return left

    def close(self, kind):
        if self.pos >= len(self.tokens) or self.tokens[self.pos].type != kind or self.tokens[self.pos].subtype != 'CLOSE':
            raise ValueError('Не закрыта скобка формулы')
        self.pos += 1

    def reference(self, value):
        sheet, address = value.rsplit('!', 1) if '!' in value else (self.sheet, value)
        sheet = sheet.strip("'").replace("''", "'")
        if '[' in sheet or ']' in sheet:
            raise ValueError('Внешняя ссылка на книгу: ' + value)
        cells = address.split(':')
        if len(cells) == 2:
            def point(cell):
                found = re.fullmatch(r'(\$?)([A-Z]+)(\$?)([0-9]+)', cell, re.I)
                if not found:
                    raise ValueError('Не поддерживается диапазон ' + value)
                return found
            a, b = map(point, cells)
            left, right = column_index_from_string(a[2]), column_index_from_string(b[2])
            top, bottom = int(a[4]), int(b[4])
            if bottom < top or right < left or (bottom-top+1)*(right-left+1) > 500:
                raise ValueError('Слишком большой или обратный диапазон ' + value)
            return ['range', [self.reference(f"'{sheet}'!{get_column_letter(c)}{'$' if a[3] else ''}{r}")
                              for r in range(top,bottom+1) for c in range(left,right+1)]]
        found = re.fullmatch(r'\$?([A-Z]+)(\$?)([0-9]+)', address, re.I)
        if not found:
            raise ValueError('Не поддерживается именованная ссылка ' + value)
        column, absolute, row = found.groups()
        if sheet == self.sheet and not absolute:
            return ['data', column.upper(), int(row)-self.row]
        return ['constant', sheet, column.upper()+row]


def references(node, kind):
    if node[0] == kind:
        yield node
    if node[0] == 'unary':
        yield from references(node[2], kind)
    elif node[0] == 'binary':
        yield from references(node[2], kind)
        yield from references(node[3], kind)
    elif node[0] in ('range', 'call'):
        for child in node[1] if node[0] == 'range' else node[2]:
            yield from references(child, kind)


class FormulaEvaluator:
    def __init__(self, frame, recipes, constants, overrides=None, origin_row=2, active_mask=None):
        self.frame, self.recipes, self.constants = frame, recipes, constants
        self.base_mask=np.ones(len(frame),dtype=bool) if active_mask is None else np.asarray(active_mask,dtype=bool)
        self.masks={}
        self.cache={}
        for column,value in (overrides or {}).items():
            old=pd.to_numeric(frame[column],errors='coerce').to_numpy(dtype=float)
            self.cache[column]=np.where(self.base_mask,value,old)
        self.active, self.errors = set(), Counter()
        self.origin_row=origin_row

    def change_mask(self,column,active=None):
        if column in self.masks: return self.masks[column]
        active=set() if active is None else active
        if column in active: raise ValueError('Циклическая зависимость '+column)
        active=active|{column}; mask=self.base_mask.copy()
        if column in self.recipes:
            for reference in references(self.recipes[column]['node'],'data'):
                child=self.change_mask(reference[1],active)
                mask |= pd.Series(child).shift(-reference[2],fill_value=False).to_numpy(dtype=bool)
        self.masks[column]=mask
        return mask

    def column(self, column):
        if column in self.cache:
            return self.cache[column]
        if column in self.active:
            raise ValueError('Циклическая зависимость расчётной колонки ' + column)
        if column not in self.recipes:
            if column not in self.frame:
                raise ValueError('Нет исходной колонки ' + column)
            self.cache[column] = pd.to_numeric(self.frame[column], errors='coerce').to_numpy(dtype=float)
            return self.cache[column]
        self.active.add(column)
        try:
            value = self.evaluate(self.recipes[column]['node'])
            result = np.broadcast_to(np.asarray(value, dtype=float), (len(self.frame),)).copy()
            result[~np.isfinite(result)] = np.nan
            recipe=self.recipes[column]; step=recipe.get('step') or 1
            if step>1:
                result[(np.arange(len(self.frame))+self.origin_row)%step!=(recipe.get('phase') or 0)]=np.nan
            if column in self.frame:
                old=pd.to_numeric(self.frame[column],errors='coerce').to_numpy(dtype=float)
                result=np.where(self.change_mask(column),result,old)
            self.cache[column] = result
            return result
        finally:
            self.active.remove(column)

    def evaluate(self, node):
        kind = node[0]
        if kind in ('number', 'text'):
            return node[1]
        if kind == 'constant':
            key = node[1]+'!'+node[2]
            if key not in self.constants:
                raise ValueError('Не прочитан коэффициент ' + key)
            return self.constants[key]
        if kind == 'data':
            values = self.column(node[1])
            return pd.Series(values).shift(-node[2]).to_numpy() if node[2] else values
        if kind == 'range':
            return [self.evaluate(child) for child in node[1]]
        if kind == 'unary':
            value = self.evaluate(node[2])
            return -value if node[1] == '-' else value
        if kind == 'binary':
            a,b = self.evaluate(node[2]),self.evaluate(node[3])
            with np.errstate(all='ignore'):
                return {'+':np.add,'-':np.subtract,'*':np.multiply,'/':np.divide,'^':np.power,
                        '=':np.equal,'<>':np.not_equal,'<':np.less,'>':np.greater,
                        '<=':np.less_equal,'>=':np.greater_equal}[node[1]](a,b)
        name, arguments = node[1], node[2]
        args = [self.evaluate(child) for child in arguments]
        if name == 'IF':
            return np.where(args[0],args[1],args[2] if len(args)>2 else 0.)
        if name == 'IFERROR':
            failed=~np.isfinite(np.broadcast_to(np.asarray(args[0],dtype=float),(len(self.frame),)))
            self.errors['IFERROR: использована подстановка из формулы']+=int((failed & self.base_mask).sum())
            return np.where(np.isfinite(args[0]),args[0],args[1])
        if name in ('SUM','AVERAGE','MIN','MAX','AND','OR'):
            flattened = [value for item in args for value in (item if isinstance(item,list) else [item])]
            arrays = np.broadcast_arrays(*[np.asarray(x) for x in flattened])
            values = np.stack(arrays)
            # Excel aggregate functions ignore blank references, but propagate
            # errors. Actual error cells are rejected when constants are read.
            errors=np.zeros(len(self.frame),dtype=bool)
            for argument in arguments:
                for ref in references(argument,'data'):
                    if ref[1] in self.recipes: errors |= ~np.isfinite(self.evaluate(ref))
            if name == 'SUM': return np.where(errors,np.nan,np.nansum(values,axis=0))
            if name == 'AVERAGE':
                count = np.isfinite(values).sum(axis=0)
                with np.errstate(all='ignore'): return np.where(errors,np.nan,np.nansum(values,axis=0)/count)
            if name == 'MIN': return np.nanmin(values,axis=0)
            if name == 'MAX': return np.nanmax(values,axis=0)
            if name == 'AND': return np.all(values,axis=0)
            return np.any(values,axis=0)
        if name in ('PROPSSI','HAPROPSSI'):
            function = PropsSI if name == 'PROPSSI' else HAPropsSI
            arrays = [np.broadcast_to(np.asarray(a), (len(self.frame),)) for a in args]
            output = np.full(len(self.frame),np.nan)
            memo = {}
            for i, row in enumerate(zip(*arrays)):
                key = tuple(value.item() if isinstance(value,np.generic) else value for value in row)
                if any(isinstance(v,(float,int)) and not np.isfinite(v) for v in key):
                    continue
                if key not in memo:
                    try: memo[key] = float(function(*key))
                    except (ValueError,OverflowError,ZeroDivisionError):
                        memo[key] = np.nan
                        self.errors[name] += 1
                output[i] = memo[key]
            return output
        with np.errstate(all='ignore'):
            if name == 'ABS': return np.abs(args[0])
            if name == 'SQRT': return np.sqrt(args[0])
            if name == 'POWER': return np.power(*args)
            if name == 'ROUND':
                scale=10.**int(args[1]); value=np.asarray(args[0])
                return np.sign(value)*np.floor(np.abs(value)*scale+.5)/scale
            if name == 'EXP': return np.exp(args[0])
            if name == 'LN': return np.log(args[0])
            if name == 'LOG10': return np.log10(args[0])
        raise ValueError('Не поддерживается функция ' + name)
