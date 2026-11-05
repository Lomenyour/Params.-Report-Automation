"""Confirmed station/unit workbook bindings and calculation dependencies."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, column_index_from_string

from data_loader import _find_header_row, _map_headers, SHORT_NAMES, RECORD_HOURS
from json_store import read_json, write_json, transaction
from parameter_mapping import parameter_for_header, header_unit
from unit_conversions import canonical_unit, unit_factor, unit_info, unit_conversion, convert_units
from workbook_formulas import FormulaParser, FormulaEvaluator, node_id, references
from workbook_corrections import CORRECTION_ROLES, correction_role
from workbook_model import compile_model

MARKER = 'GTU_WORKBOOK_PROFILE_V1'
PROFILE_SHEET = 'Профиль расчёта'
# role: (user-facing label, canonical analysis units)
ROLES = {
    'date':('Дата и время',''), 'hours_input':('Наработка исходная','ч'),
    'ambient_temperature':('Температура окружающего воздуха','°C'),
    'relative_humidity':('Относительная влажность','%'),
    'p_atm_pa':('Атмосферное давление','Па'),
    'p_nk_pa':('Абсолютное давление перед компрессором','Па'),
    'inlet_pressure_drop':('Потеря давления на входе','Па'),
    't':('Температура перед компрессором','°C'),
    'tkk':('Температура за компрессором','°C'),
    'p_kk_mpa':('Давление за компрессором','МПа'),
    'vna':('ВНА','%'), 'rpm':('Частота вращения','об/мин'),
    'power_n':('Измеренная мощность','МВт'),
    'fuel_flow':('Измеренный расход топлива',''),
    'power':('Приведённая мощность','МВт'),
    'fuel':('Приведённый расход топлива','нм³/ч'),
    'fuel_specific':('Приведённый удельный расход',''),
    'eta_compressor':('КПД компрессора','%'), 'pi_k':('Степень повышения давления',''),
    'gas_pressure':('Давление топлива','МПа'),
    'gas_temperature':('Температура топлива','°C'),
    'q_lower':('Теплота сгорания объёмная','МДж/нм³'),
    'gas_q_mass':('Теплота сгорания массовая','МДж/кг'),
    'gas_density':('Плотность газа','кг/нм³'), 'gas_c_h':('Массовое отношение C/H',''),
    'power_factor':('Коэффициент мощности',''),
    'vlo':('Перепад ВЛО','Па'), 'fgo':('Перепад ФГО','Па'),
    'fto':('Перепад ФТО','Па'), 'fgo_fto':('Перепад ФГО+ФТО','Па'),
    'exhaust_pressure':('Давление уходящих газов','кПа'),
    'exhaust_temperature':('Температура уходящих газов','°C'),
}
ROLES.update(CORRECTION_ROLES)
SENSOR_ROLES = {'ambient_temperature':'ambient_temperature','relative_humidity':'relative_humidity',
    'atmospheric_pressure':'p_atm_pa','inlet_pressure':'p_nk_pa','inlet_pressure_drop':'inlet_pressure_drop',
    'inlet_temperature':'t','outlet_temperature':'tkk','outlet_pressure':'p_kk_mpa',
    'vna':'vna','rpm':'rpm','power':'power_n','fuel_flow':'fuel_flow',
    'fuel_pressure':'gas_pressure','fuel_temperature':'gas_temperature',
    'vlo':'vlo','fgo':'fgo','fto':'fto','fgo_fto':'fgo_fto',
    'exhaust_pressure':'exhaust_pressure','exhaust_temperature':'exhaust_temperature','power_factor':'power_factor'}
REQUIRED = {'date','t','tkk','vna','p_atm_pa','p_kk_mpa','power','fuel','eta_compressor'}
_CACHE = {}


def profile_path():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'GTU_Report/workbook_mapping_profiles.json'


def clean(value):
    return re.sub(r'\s+',' ',str(value or '')).strip().casefold()


@dataclass
class WorkbookLayout:
    path: Path
    header_row: int
    headers: dict
    values: pd.DataFrame
    variants: dict = field(default_factory=dict)
    constants: dict = field(default_factory=dict)
    formula_error: str = ''
    embedded_columns: list = field(default_factory=list)
    embedded_owner: tuple | None = None


def _formulas(path, first_sheet, last_row):
    if path.suffix.lower() not in ('.xlsx','.xlsm','.xltx','.xltm'):
        raise ValueError('Для чтения формул сохраните расчётную книгу в .xlsx или .xlsm. Готовые значения можно анализировать и без формул.')
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        first=workbook.find('m:sheets',ns)[0]
        relation=first.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        relations=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        target=next(item.attrib['Target'] for item in relations if item.attrib['Id']==relation)
        xml_path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
        shared={}
        with archive.open(xml_path) as stream:
            for _,row in ET.iterparse(stream,events=['end']):
                if row.tag.rsplit('}',1)[-1]!='row': continue
                rn=int(row.attrib['r'])
                if rn>last_row: break
                for cell in row.findall('m:c',ns):
                    formula=cell.find('m:f',ns)
                    if formula is None: continue
                    address=cell.attrib['r']; text=formula.text
                    if formula.attrib.get('t')=='shared':
                        key=formula.attrib['si']
                        if text: shared[key]=(address,text)
                        elif key in shared:
                            origin,base=shared[key]
                            text=Translator('='+base,origin=origin).translate_formula(address)[1:]
                    if not text: raise ValueError('Не восстановлена общая формула '+address)
                    yield address,rn,text
                row.clear()


def read_layout(path):
    path=Path(path).resolve(); stat=path.stat(); key=(str(path),stat.st_mtime_ns,stat.st_size)
    if key in _CACHE: return copy.deepcopy(_CACHE[key])
    with pd.ExcelFile(path,engine='calamine') as book:
        if not book.sheet_names or str(book.sheet_names[0]).strip()!='Данные':
            raise ValueError('Первый лист основной книги должен называться «Данные».')
        raw=book.parse(book.sheet_names[0],header=None)
        header=_find_header_row(raw.head(25))
        if header is None: header=0
        headers={get_column_letter(i+1):None if pd.isna(value) else str(value) for i,value in enumerate(raw.iloc[header])}
        values=raw.iloc[header+1:].reset_index(drop=True).copy().astype(object)
        values.columns=list(headers)
        layout=WorkbookLayout(path,header,headers,values)
        # Ignore formula footers below the last dated source record, not data gaps.
        date_col=next((c for c,h in headers.items() if clean(h) in ('дата','date','дата/время','дата и время')),None)
        valid=pd.to_datetime(values[date_col],errors='coerce').notna() if date_col else pd.Series(True,index=values.index)
        last=header+2+int(np.flatnonzero(valid)[-1]) if valid.any() else len(raw)
        patterns={}
        try:
            for address,rn,text in _formulas(path,book.sheet_names[0],last):
                if rn<=header+1: continue
                column=re.match('[A-Z]+',address)[0]
                if column not in headers: continue
                # Normalize only unqualified relative references. Cross-sheet
                # references stay literal; coefficient addresses are never guessed.
                pieces=re.split(r'''("(?:[^"]|"")*"|'(?:[^']|'')*')''',text)
                pattern=''.join(piece if i%2 else re.sub(r'(?<![\w!$])(\$?[A-Z]{1,3})([0-9]+)',
                    lambda m:m[1]+'@'+str(int(m[2])-rn),piece) for i,piece in enumerate(pieces))
                key2=(column,pattern)
                if key2 in patterns:
                    item=patterns[key2]; item['count']+=1
                    item['last_row']=rn
                    continue
                try:
                    node=FormulaParser(text,rn).parse(); error=''
                except (ValueError,IndexError,TypeError) as exc:
                    node=None; error=str(exc)
                structural=(column,node_id(node)) if node else key2
                if structural in patterns:
                    item=patterns[structural]; item['count']+=1; item['last_row']=rn
                    patterns[key2]=item
                    continue
                item={'id':node_id(node) if node else hashlib.sha256(text.encode()).hexdigest(),
                      'formula':text,'node':node,'error':error,'count':1,'first_row':rn,'last_row':rn}
                patterns[key2]=item
                patterns[structural]=item
                layout.variants.setdefault(column,[]).append(item)
        except ValueError as exc:
            layout.formula_error=str(exc)
        if PROFILE_SHEET in book.sheet_names and not layout.variants:
            metadata=book.parse(PROFILE_SHEET,header=None)
            if metadata.iat[0,0]==MARKER:
                saved=json.loads(''.join(str(value) for value in metadata.iloc[:,1].dropna()))
                if saved.get('schema_version')!=1: raise ValueError('Неподдерживаемый встроенный профиль расчёта.')
                layout.embedded_columns=saved.get('columns',[])
                layout.embedded_owner=(saved.get('station'),saved.get('unit'))
                for col,item in saved.get('recipes',{}).items():
                    layout.variants[col]=[{**item,'count':len(values),'first_row':header+2,'last_row':last}]
                layout.constants=saved.get('constants',{})
                layout.formula_error=''
        needed={ref[1]+'!'+ref[2] for items in layout.variants.values() for item in items if item['node']
                for ref in references(item['node'],'constant')}
        sheets={}
        for reference in needed:
            sheet,address=reference.rsplit('!',1)
            if reference in layout.constants: continue
            if sheet not in book.sheet_names:
                continue
            if sheet not in sheets: sheets[sheet]=raw if sheet==book.sheet_names[0] else book.parse(sheet,header=None)
            found=re.fullmatch(r'([A-Z]+)([0-9]+)',address)
            row,col=int(found[2])-1,column_index_from_string(found[1])-1
            frame=sheets[sheet]
            if row>=len(frame) or col>=len(frame.columns): continue
            value=frame.iat[row,col]
            if pd.notna(value):
                try: layout.constants[reference]=float(value)
                except (TypeError,ValueError): layout.constants[reference]=str(value)
    for variants in layout.variants.values():
        for item in variants:
            count=item['count']; span=item['last_row']-item['first_row']
            step=span//(count-1) if count>1 and span%(count-1)==0 else 1
            item['step']=item.get('step') or (step if step in (1,2) else 1)
            item['phase']=item.get('phase',item['first_row']%item['step'])
    _CACHE.clear(); _CACHE[key]=copy.deepcopy(layout)
    return layout


def suggested_role(header,station):
    correction=correction_role(header)
    if correction: return correction
    text=clean(header)
    physical=parameter_for_header(header,station)
    if physical in SENSOR_ROLES: return SENSOR_ROLES[physical]
    canonical=_map_headers([header])[0][0]
    for role,names in SHORT_NAMES.items():
        if canonical in names and role in ROLES: return role
    name=text.split(',')[0].strip()
    if name in ('наработка','наработка ч','наработка, ч'): return 'hours_input'
    if name in ('ρ','ρгаза','плотность газа'): return 'gas_density'
    if name in ('c/h','с/н'): return 'gas_c_h'
    return ''


def main_recipe(variants):
    """Only a unique most frequent structure is eligible for automatic use."""
    if not variants: return None
    count=max(item['count'] for item in variants)
    leaders=[item for item in variants if item['count']==count]
    return leaders[0] if len(leaders)==1 else None


def column_variants(layout,column,role):
    variants=layout.variants.get(column,[])
    if variants or role not in CORRECTION_ROLES: return variants
    # Some station books supply an explicitly constant correction as numbers,
    # not formulas (e.g. kPη=1). Expose the proposal for confirmation; never
    # extrapolate a varying, partial or nonnumeric correction this way.
    date_column=next((key for key,header in layout.headers.items()
                      if clean(header) in ('дата','date','дата/время','дата и время')),None)
    if date_column is None: return []
    valid=pd.to_datetime(layout.values[date_column],errors='coerce').notna()
    values=pd.to_numeric(layout.values.loc[valid,column],errors='coerce')
    if values.empty or values.isna().any() or not np.isfinite(values).all() or values.nunique()!=1: return []
    value=float(values.iloc[0]);node=['number',value]
    return [{'id':node_id(node),'formula':f'{value:g}','node':node,'error':'','count':len(values),
             'first_row':layout.header_row+2,'last_row':layout.header_row+1+len(values),
             'step':1,'phase':0,'constant_value':True}]


def suggestions(layout,station,unit):
    data=read_json(profile_path(),{'schema_version':1,'profiles':{}})
    if data.get('schema_version')!=1 or not isinstance(data.get('profiles'),dict):
        raise ValueError('Повреждён справочник основной книги; файл не изменён.')
    owner=data['profiles'].get(f'{station}|{unit}',{})
    signature=hashlib.sha256(json.dumps(sorted(clean(h) for h in layout.headers.values()),ensure_ascii=False).encode()).hexdigest()
    ordered_signature=node_id(list(layout.headers.values()))
    candidates=[*owner.get('history',[]),owner.get('current',{})]
    matched=next((record for record in reversed(candidates) if record.get('ordered_signature')==ordered_signature),None)
    matched=matched or next((record for record in reversed(candidates) if record.get('signature')==signature),None)
    record=matched or owner.get('current',{})
    saved=record.get('columns',[])
    by_position={row['column']:row for row in saved} if record.get('ordered_signature')==ordered_signature else {}
    # Exact unique headers survive moves. Duplicates require manual resolution.
    counts=Counter(clean(h) for h in layout.headers.values() if h)
    old_counts=Counter(clean(row['header']) for row in saved if row.get('header'))
    old={clean(row['header']):row for row in saved if row.get('header') and old_counts[clean(row['header'])]==1}
    embedded_rows=layout.embedded_columns if layout.embedded_owner in (None,(station,str(unit))) else []
    embedded_counts=Counter(clean(row['header']) for row in embedded_rows if row.get('header'))
    embedded={clean(row['header']):row for row in embedded_rows if row.get('header') and embedded_counts[clean(row['header'])]==1}
    rows=[]
    for col,header in layout.headers.items():
        previous=(old.get(clean(header)) or embedded.get(clean(header))) if header and counts[clean(header)]==1 else by_position.get(col)
        role=previous.get('role','') if previous else suggested_role(header,station)
        # Upgrade old generic correction assignments once. New explicit helper
        # choices carry mapping_version and must remain user-owned thereafter.
        upgraded=bool(previous and not role and not previous.get('mapping_version') and correction_role(header))
        if upgraded: role=correction_role(header)
        if previous is None and not header and col=='A' and layout.headers.get('B')=='Дата': role='hours_input'
        unit_text=previous.get('unit','') if previous else header_unit(header)
        unit_inferred=bool(role and not unit_text and ROLES[role][1])
        if role and not unit_text: unit_text=ROLES[role][1]
        if role=='q_lower' and ('/кг' in unit_text.lower()): role='gas_q_mass'
        # Syz Qнр is stored in MJ/kg despite its volumetric-looking legacy header.
        if role=='q_lower' and any('Результаты!' in item['formula'] and '/' in item['formula'] for item in layout.variants.get(col,[])):
            role='gas_q_mass'; unit_text='МДж/кг'
        variants=column_variants(layout,col,role)
        selected=main_recipe(variants)
        changed=bool(previous and previous.get('recipe') and (selected is None or selected['id']!=previous['recipe']))
        rows.append({'column':col,'header':header or '', 'role':role,'unit':canonical_unit(unit_text) or unit_text,
                     'kind':'service' if role in ('date','hours_input') else previous.get('kind') if previous and not upgraded else ('computed' if variants or role in CORRECTION_ROLES or role in ('power','fuel','fuel_specific','eta_compressor','pi_k','gas_q_mass','gas_c_h') else 'measured'),
                     'recipe':selected['id'] if selected else '', 'variants':variants,'changed':changed,'unit_inferred':unit_inferred,
                     'formula_conflict':bool(variants and selected is None)})
    # A calculated conversion of measured flow is a helper, not a second sensor.
    for role in set(r['role'] for r in rows if r['role']):
        candidates=[r for r in rows if r['role']==role]
        if len(candidates)<2: continue
        measured=[r for r in candidates if r['kind']=='measured']
        canonical=[r for r in candidates if _map_headers([r['header']])[0][0] in SHORT_NAMES.get('p_nk_pa',[])] if role=='inlet_pressure_drop' else []
        chosen=measured[0] if len(measured)==1 else canonical[0] if len(canonical)==1 else None
        for row in candidates:
            if row is not chosen: row['role']=''
    return rows


@dataclass
class BookSetup:
    station: str
    unit: str
    columns: list
    recipes: dict
    constants: dict
    stamp: tuple
    header_row: int = 0

    @property
    def bindings(self):
        return {row['role']:row for row in self.columns if row.get('role')}

    @property
    def sensor_columns(self):
        result={parameter:self.bindings[role]['column'] for parameter,role in SENSOR_ROLES.items()
                if role in self.bindings and self.bindings[role]['kind']=='measured'}
        for row in self.columns:
            if row['kind']=='measured' and not row['role'] and row['header']:
                result['aux:'+hashlib.sha256(clean(row['header']).encode()).hexdigest()[:16]]=row['column']
        return result

    def import_headers(self,headers):
        result=dict(headers)
        for row in self.columns:
            if row['role'] and row['unit']:
                label=str(result.get(row['column']) or ROLES[row['role']][0]).split(',',1)[0]
                result[row['column']]=label+', '+row['unit']
        return result

    def canonical(self,values):
        result=pd.DataFrame(index=values.index)
        for role,row in self.bindings.items():
            if role not in ROLES or role in ('gas_density','gas_c_h','gas_q_mass','rpm','fuel_flow','relative_humidity','inlet_pressure_drop','exhaust_pressure','exhaust_temperature'):
                continue
            source=values[row['column']]
            if role=='date': result[role]=pd.to_datetime(source,errors='coerce'); continue
            result[role]=pd.to_numeric(source,errors='coerce')
            target=ROLES[role][1]
            if row['unit'] and target and role not in ('hours_input','q_lower'):
                result[role] = convert_units(result[role],row['unit'],target)
        if 'p_nk_pa' not in result and 'inlet_pressure_drop' in self.bindings:
            row=self.bindings['inlet_pressure_drop']
            result['p_nk_pa']=pd.to_numeric(values[row['column']],errors='coerce')*unit_factor(row['unit'] or 'Па','Па')
        result['hours']=np.arange(len(values),dtype=float)*RECORD_HOURS
        if 'hours_input' not in result: result['hours_input']=np.nan
        result['excel_row']=np.arange(len(values))+self.header_row+2
        result=result.reset_index(drop=True)
        result.attrs['inlet_pressure_kind']='absolute' if 'p_nk_pa' in self.bindings else 'drop'
        return result

    def audit(self,source):
        dates=pd.to_datetime(source['date'],errors='coerce')
        valid=dates.dropna()
        if valid.duplicated().any():
            raise ValueError('На листе «Данные» повторяются временные метки.')
        from periods import LOW_POWER
        working=pd.to_numeric(source['power'],errors='coerce')>LOW_POWER
        summary={'датированных строк':int(valid.size),'недатированных строк':int(dates.isna().sum()),
                 'часовой пояс':'не указан в книге' if valid.dt.tz is None else str(valid.dt.tz)}
        for key in ('power','fuel','fuel_specific','eta_compressor'):
            if key in source:
                summary['пропуски '+ROLES[key][0]]=int(pd.to_numeric(source[key],errors='coerce').isna().sum())
        for key in ('vlo','fgo','fto','fgo_fto'):
            if key in source: summary['отрицательные '+key]=int((working & (source[key]<0)).sum())
        return summary

    def metadata(self):
        headers=self.import_headers({row['column']:row['header'] for row in self.columns})
        columns=[{**row,'source_header':row['header'],'header':headers[row['column']]} for row in self.columns]
        model,column_ids,source_ids=compile_model(columns,self.recipes,self.constants,self.header_row+2)
        return {'schema_version':1,'station':self.station,'unit':self.unit,'columns':columns,
                'recipes':self.recipes,'constants':self.constants,'calculation_model':model.to_dict(),
                'source_bindings':{'columns':column_ids,'coefficients':source_ids}}

    def recalculate(self,values,*,passport=None,changed_dates=None):
        overrides={}
        recipes=copy.deepcopy(self.recipes)
        constants=dict(self.constants)
        if passport is not None:
            from gas_passport import gas_values
            gas=gas_values(passport,values[self.bindings['date']['column']])
            for role,key in (('gas_density','density_kg_per_nm3'),('gas_c_h','carbon_hydrogen_ratio'),('q_lower','q_lower_mj_per_nm3')):
                if role in self.bindings: overrides[self.bindings[role]['column']]=np.asarray(gas[key])
            if 'gas_q_mass' in self.bindings:
                overrides[self.bindings['gas_q_mass']['column']]=gas['q_lower_mj_per_nm3']/gas['density_kg_per_nm3']
            for recipe in recipes.values():
                if recipe.get('gas_density_conversion'):
                    recipe['node'][3]=['constant','Паспорт газа','density']
                    constants['Паспорт газа!density']=gas['density_kg_per_nm3']
        mask=None if changed_dates is None else pd.DatetimeIndex(pd.to_datetime(values[self.bindings['date']['column']])).isin(changed_dates)
        model,column_ids,_=compile_model(self.columns,recipes,constants,self.header_row+2)
        frame=values.rename(columns=column_ids)
        evaluator=model.evaluator(frame,{column_ids[key]:value for key,value in overrides.items()},mask)
        diagnostics={}
        used={ref[1] for recipe in recipes.values() if recipe['node'] for ref in references(recipe['node'],'data')}
        for column in sorted(used-set(recipes)):
            if column in values and column not in overrides:
                missing=~np.isfinite(pd.to_numeric(values[column],errors='coerce').to_numpy(dtype=float))
                count=int((missing & evaluator.base_mask).sum())
                if count: diagnostics['Нет входного значения '+column]=count
        calculated={}
        for column,recipe in self.recipes.items():
            result=evaluator.column(column_ids[column])
            # Every-second-row summaries keep the workbook's established phase.
            step=recipe.get('step') or 1; phase=recipe.get('phase') or 0
            if step>1:
                result=result.copy(); result[(np.arange(len(values))+self.header_row+2)%step!=phase]=np.nan
            calculated[column]=result
        for column,result in calculated.items():
            if mask is None: values[column]=result
            else:
                changed=evaluator.change_mask(column_ids[column])
                values[column]=values[column].astype(object)
                values.loc[changed,column]=result[changed]
        for column,value in overrides.items():
            if mask is None: values[column]=value
            else:
                values[column]=values[column].astype(object)
                values.loc[mask,column]=np.asarray(value)[mask]
        return {**dict(evaluator.errors),**diagnostics}


def confirm(layout,station,unit,rows,*,save=True):
    if layout.embedded_owner and layout.embedded_owner!=(station,str(unit)):
        raise ValueError('Встроенный профиль расчёта относится к другой ТЭЦ или ГТУ.')
    if len(rows)!=len(layout.headers) or {r.get('column') for r in rows}!=set(layout.headers):
        raise ValueError('Набор колонок изменился. Повторно откройте проверку книги.')
    columns=[]; recipes={}; assigned=set()
    for row in rows:
        col=row['column']; role=row.get('role',''); kind=row.get('kind','measured')
        if role and role not in ROLES: raise ValueError('Неизвестный параметр '+role)
        if role in assigned: raise ValueError('Параметр назначен дважды: '+ROLES[role][0])
        if role: assigned.add(role)
        source_unit=str(row.get('unit','')).strip()
        target_unit=ROLES.get(role,('',''))[1]
        if source_unit and target_unit and role not in ('hours_input','q_lower','gas_q_mass','gas_density','fuel_specific'):
            unit_conversion(source_unit,target_unit)
        if role in ('date','hours_input'): kind='service'
        if kind not in ('measured','computed','service'): raise ValueError('Неизвестный тип колонки '+col)
        if kind=='service' and role not in ('date','hours_input'):
            raise ValueError('Служебный тип предназначен только для даты и наработки: '+col)
        if role in CORRECTION_ROLES and kind!='computed':
            raise ValueError('Поправка должна иметь расчётный тип: '+col)
        variants=column_variants(layout,col,role)
        selected=main_recipe(variants)
        # Legacy loss formulas are intentionally excluded: the app owns them.
        loss=any(word in clean(layout.headers[col]) for word in ('недовыработка','перерасход'))
        if kind=='computed' and selected and role not in ('date','hours_input') and not loss:
            recipes[col]={k:selected.get(k) for k in ('id','formula','node','error','step','phase','count','constant_value')}
            node=selected['node']; info=unit_info(row.get('unit',''))
            # Recognized mass-to-normal-volume conversion; this is not a
            # dimensionless correction factor. The passport supplies density.
            if node and node[:2]==['binary','/'] and node[3][0]=='number' and 0<node[3][1]<5:
                if '3600.0' in json.dumps(node[2]) and info and info['dimension']=='normal_volume_flow':
                    recipes[col]['gas_density_conversion']=True
        columns.append({'column':col,'header':layout.headers[col] or '', 'role':role,
                        'unit':str(row.get('unit','')).strip(),'kind':kind,'recipe':selected['id'] if selected else '',
                        'mapping_version':2,'formula_conflict':bool(variants and selected is None)})
    excluded={col for col,h in layout.headers.items() if any(word in clean(h) for word in ('недовыработка','перерасход'))}
    # Blank-headed averages/footers of the legacy losses must not run either.
    changed=True
    while changed:
        changed=False
        for col,item in list(recipes.items()):
            if item['node'] and any(ref[1] in excluded for ref in references(item['node'],'data')):
                excluded.add(col); del recipes[col]; changed=True
    # Any unsupported formula with no semantic role is a preserved helper;
    # reject it only if a required calculation actually depends on it.
    for col,item in list(recipes.items()):
        if item['error'] and not next(row['role'] for row in columns if row['column']==col):
            excluded.add(col); del recipes[col]
    missing=REQUIRED-assigned
    if not assigned.intersection({'p_nk_pa','inlet_pressure_drop'}): missing.add('p_nk_pa')
    if missing: raise ValueError('Назначьте параметры: '+', '.join(ROLES[k][0] for k in sorted(missing)))
    setup=BookSetup(station,str(unit),columns,recipes,copy.deepcopy(layout.constants),
        (str(layout.path),layout.path.stat().st_mtime_ns,layout.path.stat().st_size),layout.header_row)
    if save:
        with transaction():
            data=read_json(profile_path(),{'schema_version':1,'profiles':{}})
            owner=data['profiles'].setdefault(f'{station}|{unit}',{'history':[]})
            signature=hashlib.sha256(json.dumps(sorted(clean(h) for h in layout.headers.values()),ensure_ascii=False).encode()).hexdigest()
            current={'columns':columns,'signature':signature,'ordered_signature':node_id(list(layout.headers.values())),
                     'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
            if owner.get('current') and owner['current']['columns']!=columns: owner['history'].append(owner['current'])
            owner['current']=current
            write_json(profile_path(),data)
    return setup


def validate_recalculation(setup):
    for row in setup.columns:
        if row.get('formula_conflict') and row['kind']=='computed':
            raise ValueError('Колонка '+row['column']+': разные формулы встречаются одинаково часто. Уточните основную зависимость в исходной книге.')
        if row['role'] in CORRECTION_ROLES and row['column'] not in setup.recipes:
            raise ValueError('Для поправки '+ROLES[row['role']][0]+' ('+row['column']+') нет формулы или подтверждённой полной постоянной колонки.')
    for column,recipe in setup.recipes.items():
        if recipe.get('error') or recipe.get('node') is None:
            raise ValueError(f"Колонка {column}: {recipe.get('error') or 'нет поддерживаемой формулы'}")
        for reference in references(recipe['node'],'constant'):
            key=reference[1]+'!'+reference[2]
            if key not in setup.constants: raise ValueError('В текущей книге отсутствует коэффициент '+key)
        for reference in references(recipe['node'],'data'):
            row=next((r for r in setup.columns if r['column']==reference[1]),None)
            if row and row['kind']=='computed' and row['role'] not in ('date','hours_input') and row['column'] not in setup.recipes:
                raise ValueError(f"Для {column} нужна неподдерживаемая формула {row['column']}.")
    for role in ('power','fuel','fuel_specific','eta_compressor'):
        row=setup.bindings.get(role)
        if row and row['column'] not in setup.recipes:
            raise ValueError('Для новых строк нет формулы: '+ROLES[role][0]+'. Нужна книга с формулами либо встроенным профилем расчёта.')
