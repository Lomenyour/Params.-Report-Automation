"""Parameter-based calculation model, independent of Excel files and addresses.

The workbook adapter supplies arrays, units, expressions and coefficient values.
The same serializable model can later be loaded from a database repository.
"""
from dataclasses import dataclass
import copy
import hashlib
import json

from workbook_formulas import FormulaEvaluator, references


def select_recipes(recipes, targets):
    """Select only requested outputs and their transitive formula dependencies."""
    selected=set(); pending=list(targets)
    while pending:
        key=pending.pop()
        if key in selected or key not in recipes: continue
        selected.add(key)
        if recipes[key]['node'] is not None:
            pending.extend(ref[1] for ref in references(recipes[key]['node'],'data'))
    return {key:value for key,value in recipes.items() if key in selected}


def calculation_scope(columns, recipes):
    """The adapter explicitly names outputs; unassigned formulas are dependencies only."""
    targets=[row['column'] for row in columns if row.get('role') and row['kind']=='computed']
    selected=select_recipes(recipes,targets)
    return {'targets':targets,'calculated':list(selected),
            'dependencies':[key for key in selected if key not in targets],
            'preserved':[row['column'] for row in columns
                         if row['kind']=='computed' and row['column'] not in selected and row['column'] not in targets]}


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def map_node(node, data, constant):
    if node is None: return None
    kind=node[0]
    if kind=='data': return ['data',data(node[1]),node[2]]
    if kind=='constant': return ['constant','coefficients',constant(node[1]+'!'+node[2])]
    if kind=='unary': return [kind,node[1],map_node(node[2],data,constant)]
    if kind=='binary': return [kind,node[1],map_node(node[2],data,constant),map_node(node[3],data,constant)]
    if kind=='range': return [kind,[map_node(child,data,constant) for child in node[1]]]
    if kind=='call': return [kind,node[1],[map_node(child,data,constant) for child in node[2]]]
    return copy.deepcopy(node)


@dataclass
class CalculationModel:
    parameters: dict
    recipes: dict
    coefficients: dict
    record_origin: int = 2

    def to_dict(self):
        content={'schema_version':1,'parameters':self.parameters,'recipes':self.recipes,
                 'coefficients':self.coefficients,'record_origin':self.record_origin}
        return {**copy.deepcopy(content),'revision':_digest(content)}

    @classmethod
    def from_dict(cls, content):
        if content.get('schema_version')!=1: raise ValueError('Неподдерживаемая версия расчётной модели.')
        model=cls(*(copy.deepcopy(content[key]) for key in ('parameters','recipes','coefficients')),content['record_origin'])
        if model.to_dict()['revision']!=content.get('revision'):
            raise ValueError('Версия расчётной модели не соответствует её содержимому.')
        return model

    def evaluator(self, values, overrides=None, active_mask=None):
        constants={'coefficients!'+key:value for key,value in self.coefficients.items()}
        return FormulaEvaluator(values,self.recipes,constants,overrides,self.record_origin,active_mask,
                                labels={key:value['label'] for key,value in self.parameters.items()})

    def execution_order(self, targets):
        """Validate the reachable graph before any numeric evaluation or writes."""
        ordered=[]; visiting=[]; visited=set()
        def visit(key):
            label=self.parameters.get(key,{}).get('label',key)
            if key not in self.parameters:
                raise ValueError('Не найден входной параметр '+label)
            if key in visited: return
            if key in visiting:
                chain=visiting[visiting.index(key):]+[key]
                raise ValueError('Циклическая зависимость расчётной колонки '+
                                 ' → '.join(self.parameters[item]['label'] for item in chain))
            if key not in self.recipes:
                if self.parameters[key]['kind']=='computed':
                    raise ValueError('Нужна неподдерживаемая формула параметра '+label)
                return
            recipe=self.recipes[key]
            if recipe['node'] is None:
                raise ValueError('Нет поддерживаемой формулы параметра '+label)
            visiting.append(key)
            for ref in references(recipe['node'],'data'): visit(ref[1])
            visiting.pop(); visited.add(key); ordered.append(key)
        for target in targets: visit(target)
        return ordered


def compile_model(columns, recipes, constants, record_origin=2):
    """Return a neutral model plus adapter-only source maps for audit/export."""
    column_ids={}; parameters={}
    for row in columns:
        identifier=row['role'] or 'aux_'+_digest(row.get('source_header') or row['header'] or row['column'])[:16]
        if identifier in parameters: identifier+='_'+row['column']
        column_ids[row['column']]=identifier
        parameters[identifier]={'label':row['header'] or row['column'],'unit':row['unit'],'kind':row['kind']}
    source_ids={}; coefficients={}; compiled={}
    for column,recipe in sorted(recipes.items(),key=lambda pair:column_ids[pair[0]]):
        parameter=column_ids[column]
        def coefficient(source):
            if source not in source_ids:
                source_ids[source]=f'{parameter}.c{len(source_ids)+1}'
            identifier=source_ids[source]
            if source in constants: coefficients[identifier]=constants[source]
            return identifier
        compiled[parameter]={key:copy.deepcopy(recipe[key]) for key in ('step','phase','gas_density_conversion') if key in recipe}
        compiled[parameter]['node']=map_node(recipe['node'],lambda key:column_ids[key],coefficient)
    return CalculationModel(parameters,compiled,coefficients,record_origin),column_ids,source_ids
