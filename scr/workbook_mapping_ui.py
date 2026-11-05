"""Workbook mapping and read-only calculation views for both GUI adapters."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from workbook_profile import ROLES, confirm, main_recipe, column_variants
from workbook_formulas import references
from workbook_model import compile_model
from formula_display import FormulaNotation, parameter_symbols

KIND_LABELS={'measured':'Измеренный','computed':'Расчётный','service':'Служебный'}


def application_columns(rows):
    owned={row['column'] for row in rows if any(word in str(row['header']).casefold() for word in ('недовыработка','перерасход'))}
    while True:
        expanded=owned|{row['column'] for row in rows if row['kind']=='computed'
                       for selected in [main_recipe(row['variants'])] if selected and selected['node']
                       if any(ref[1] in owned for ref in references(selected['node'],'data'))}
        if expanded==owned: break
        owned=expanded
    return owned


def merge_mapping_rows(layout, original, submitted):
    """The view edits only named rows; hidden rows remain owned by the adapter."""
    if not isinstance(submitted,list) or not all(isinstance(row,dict) for row in submitted):
        raise ValueError('Некорректный список видимых колонок.')
    visible={row['column'] for row in original if str(layout.headers[row['column']] or '').strip()}
    if len(submitted)!=len(visible) or {row.get('column') for row in submitted}!=visible:
        raise ValueError('Набор видимых колонок изменился. Повторите проверку книги.')
    changes={row['column']:row for row in submitted}
    return [{**row,**{key:changes[row['column']].get(key,row.get(key,'')) for key in ('role','unit','kind','recipe')}}
            if row['column'] in changes else dict(row) for row in original]


def formula_view(layout,rows):
    """Compile current unsaved assignments, then format the neutral model."""
    columns=[];recipes={};selected={};issues={}
    normalized=[]
    for row in rows:
        role=row.get('role','')
        if role and role not in ROLES:raise ValueError('Неизвестный параметр '+role)
        col=row['column'];variants=column_variants(layout,col,role)
        normalized.append({**row,'variants':variants})
        columns.append({**row,'header':layout.headers[col] or ''})
        choice=main_recipe(variants)
        if choice:selected[col]=choice
        if row['kind']!='computed' or role in ('date','hours_input') or not choice:continue
        if choice['node'] is None:issues[col]=choice['error'];continue
        missing={ref[1] for ref in references(choice['node'],'data')}-set(layout.headers)
        if missing:issues[col]='Не найдены входные столбцы: '+', '.join(sorted(missing));continue
        recipes[col]={key:choice.get(key) for key in ('node','step','phase')}
    owned=application_columns(normalized)
    recipes={col:recipe for col,recipe in recipes.items() if col not in owned}
    model,column_ids,source_ids=compile_model(columns,recipes,layout.constants,layout.header_row+2)
    symbols=parameter_symbols(columns,column_ids);sources={identifier:source for source,identifier in source_ids.items()}
    by_id={column_ids[row['column']]:row for row in columns}
    result=[]
    for row in normalized:
        col=row['column'];identifier=column_ids[col]
        if row['kind']!='computed' or not str(row['header'] or '').strip():continue
        choice=selected.get(col);formatter=FormulaNotation(symbols);expression='';error=issues.get(col,'')
        if identifier in model.recipes:
            try:expression=symbols[identifier]+' = '+formatter.render(model.recipes[identifier]['node'])
            except (ValueError,KeyError,TypeError) as exc:error=str(exc)
        coefficients=[{'symbol':symbol,'source':sources[key],
                       'value':layout.constants.get(sources[key]),'missing':sources[key] not in layout.constants}
                      for key,symbol in formatter.coefficients.items()]
        dependencies=[{'symbol':symbols[key],'label':ROLES.get(by_id[key]['role'],(by_id[key]['header'] or 'Безымянный вспомогательный столбец',''))[0],
                       'source':by_id[key]['column'],'unit':by_id[key]['unit'],'offset':offset}
                      for key,offset in formatter.dependencies]
        result.append({'column':col,'label':ROLES.get(row['role'],(row['header'],''))[0],
                       'display_formula':expression,'error':error,'application_owned':col in owned,
                       'constant_value':bool(choice and choice.get('constant_value')),
                       'source_formula':choice['formula'] if choice else '',
                       'count':choice['count'] if choice else 0,'total':sum(v['count'] for v in row['variants']),
                       'coefficients':coefficients,'dependencies':dependencies,
                       'alternatives':[{'formula':variant['formula'],'count':variant['count']} for variant in row['variants'] if variant is not choice]})
    return {'rows':result}


def dialog_payload(layout, rows):
    owned=application_columns(rows)
    warnings=[layout.formula_error] if layout.formula_error else []
    conflicts=[row['column'] for row in rows if row.get('formula_conflict')]
    if conflicts: warnings.append('Нет единственной основной формулы: '+', '.join(conflicts)+'. Уточните выражения в книге перед импортом.')
    changed=[row['column'] for row in rows if row.get('changed')]
    if changed: warnings.append('Изменились формулы: '+', '.join(changed)+'. Проверьте расчётные выражения.')
    return {'kind':'bookMapping','title':'Основная книга — параметры и расчёт',
            'note':' '.join(warnings),
            'roles':[{'value':'','label':'Вспомогательная колонка'}]+[{'value':key,'label':value[0]} for key,value in ROLES.items()],
            'rows':[{**{key:row[key] for key in ('column','header','role','unit','kind','recipe')},
                     'variants':[{key:item.get(key) for key in ('id','formula','count','error','constant_value')} for item in row['variants']],
                     'application_owned':row['column'] in owned}
                    for row in rows if str(row['header'] or '').strip()]}


def corrections_payload(setup):
    groups=[]
    for row in setup.columns:
        recipe=setup.recipes.get(row['column'])
        if not recipe: continue
        sources=list(dict.fromkeys(ref[1]+'!'+ref[2] for ref in references(recipe['node'],'constant'))) if recipe['node'] else []
        if not sources and not row['role'].startswith('correction_'): continue
        groups.append({'label':ROLES[row['role']][0] if row['role'] else row['header'] or row['column'],
                       'column':row['column'],'formula':('Постоянное значение из числового столбца: ' if recipe.get('constant_value') else '')+recipe['formula'],
                       'coefficients':[{'source':source,'value':setup.constants.get(source),'missing':source not in setup.constants} for source in sources]})
    return {'kind':'bookCorrections','title':f'Поправки ГТ-{setup.unit} — коэффициенты из книги',
            'note':'Коэффициенты прочитаны по ссылкам выбранных формул. Числа внутри выражений показаны в самих формулах. Для изменения коэффициентов отредактируйте основную книгу и повторите проверку.',
            'groups':groups,'revision':setup.metadata()['calculation_model']['revision'][:12]}


def show_text(parent,title,content):
    window=tk.Toplevel(parent);window.title(title);window.geometry('950x650');window.transient(parent)
    text=ScrolledText(window,wrap='word',padx=12,pady=12);text.pack(fill='both',expand=True)
    text.insert('1.0',content);text.configure(state='disabled')
    ttk.Button(window,text='Закрыть',command=window.destroy).pack(pady=10)
    return window


class BookCorrectionsDialog:
    def __init__(self,parent,setup):
        payload=corrections_payload(setup)
        content=payload['note']+'\nВерсия модели: '+payload['revision']+'\n\n'
        for group in payload['groups']:
            content+=group['label']+'\n'+group['formula']+'\n'
            content+='\n'.join(f"{item['source']} = {item['value'] if not item['missing'] else 'НЕ ПРОЧИТАН'}" for item in group['coefficients'])+'\n\n'
        self.window=show_text(parent,payload['title'],content)


class BookMappingDialog(tk.Toplevel):
    def __init__(self,parent,layout,rows,station,unit):
        super().__init__(parent)
        self.result=None;self.layout=layout;self.rows=rows;self.station=station;self.unit=unit
        self.title('Основная книга — параметры и расчёт');self.geometry('1100x700');self.minsize(800,500);self.transient(parent)
        toolbar=ttk.Frame(self,padding=12);toolbar.pack(fill='x')
        ttk.Button(toolbar,text='Показать расчётные формулы',command=self.show_formulas).pack(side='left')
        ttk.Button(toolbar,text='Показать коэффициенты',command=self.show_coefficients).pack(side='left',padx=8)
        note=dialog_payload(layout,rows)['note']
        if note: ttk.Label(toolbar,text=note,wraplength=900).pack(side='left',padx=12)
        canvas=tk.Canvas(self,highlightthickness=0);scroll=ttk.Scrollbar(self,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
        body=ttk.Frame(canvas,padding=12);anchor=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(anchor,width=event.width))
        for col,title in enumerate(('Колонка книги','Параметр','Единицы','Тип')):
            ttk.Label(body,text=title).grid(row=0,column=col,sticky='w',pady=8)
        body.columnconfigure(1,weight=1)
        self.fields=[];roles=['Вспомогательная колонка']+[label for label,_ in ROLES.values()]
        for index,row in enumerate((row for row in rows if str(row['header'] or '').strip()),start=1):
            ttk.Label(body,text=f"{row['column']} — {row['header']}",wraplength=260).grid(row=index,column=0,sticky='w',pady=4,padx=(0,12))
            role=tk.StringVar(value=ROLES[row['role']][0] if row['role'] else roles[0]);unit_var=tk.StringVar(value=row['unit'])
            kind=tk.StringVar(value=KIND_LABELS[row['kind']])
            ttk.Combobox(body,textvariable=role,values=roles,state='readonly',height=12,width=48).grid(row=index,column=1,sticky='ew',padx=(0,12))
            ttk.Entry(body,textvariable=unit_var,width=14).grid(row=index,column=2,padx=(0,12))
            ttk.Combobox(body,textvariable=kind,values=list(KIND_LABELS.values()),state='readonly',width=14).grid(row=index,column=3)
            self.fields.append((row,role,unit_var,kind))
        actions=ttk.Frame(self,padding=12);actions.pack(fill='x')
        ttk.Button(actions,text='Отмена',command=self.destroy).pack(side='right')
        ttk.Button(actions,text='Подтвердить книгу',command=self.accept).pack(side='right',padx=8)
        self.grab_set()

    def show_formulas(self):
        content='t — текущая строка, t+1 — следующая строка.\n\n'
        for item in formula_view(self.layout,self.current_rows())['rows']:
            content+=item['label']+'\n'+(item['display_formula'] or ('Расчёт программы' if item['application_owned'] else item['error'] or 'Нет формулы'))
            content+='\nExcel: '+item['source_formula']+'\n'
            content+='\n'.join(f"{coefficient['symbol']}: {coefficient['source']} = {coefficient['value']}" for coefficient in item['coefficients'])+'\n\n'
        show_text(self,'Расчётные формулы',content)

    def show_coefficients(self):
        content='Коэффициенты выбранных выражений из текущей книги.\n\n'
        for row in formula_view(self.layout,self.current_rows())['rows']:
            items=row['coefficients']
            if not items and not row['constant_value']:continue
            content+=row['label']+'\n'+row['display_formula']+'\n'
            content+='\n'.join(f"{item['source']} = {item['value'] if not item['missing'] else 'НЕ ПРОЧИТАН'}" for item in items)+'\n\n'
        show_text(self,'Коэффициенты из книги',content)

    def accept(self):
        try:self.result=confirm(self.layout,self.station,self.unit,self.current_rows(),save=False)
        except ValueError as error:
            messagebox.showerror('Проверьте основную книгу',str(error),parent=self);return
        self.destroy()

    def current_rows(self):
        roles={label:key for key,(label,_) in ROLES.items()};kinds={label:key for key,label in KIND_LABELS.items()}
        rows=[{**old,'role':roles.get(role.get(),''),'unit':unit.get(),'kind':kinds[kind.get()]} for old,role,unit,kind in self.fields]
        return merge_mapping_rows(self.layout,self.rows,rows)
