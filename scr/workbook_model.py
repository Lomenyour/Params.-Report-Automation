"""Parameter-based calculation model, independent of Excel files and addresses.

The workbook adapter supplies arrays, units, expressions and coefficient values.
The same serializable model can later be loaded from a database repository.
"""
from dataclasses import dataclass
import copy
import hashlib
import json

from workbook_formulas import FormulaEvaluator


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
        return FormulaEvaluator(values,self.recipes,constants,overrides,self.record_origin,active_mask)


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
