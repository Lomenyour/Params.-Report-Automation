"""Workbook mapping and read-only calculation views for both GUI adapters."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from workbook_profile import ROLES, confirm, main_recipe
from workbook_formulas import references

KIND_LABELS={'measured':'Измеренный','computed':'Расчётный','service':'Служебный'}


def dialog_payload(layout, rows):
    owned={row['column'] for row in rows if any(word in str(row['header']).casefold() for word in ('недовыработка','перерасход'))}
    while True:
        expanded=owned|{row['column'] for row in rows if row['kind']=='computed'
                       for selected in [main_recipe(row['variants'])] if selected and selected['node']
                       if any(ref[1] in owned for ref in references(selected['node'],'data'))}
        if expanded==owned: break
        owned=expanded
    warnings=[layout.formula_error] if layout.formula_error else []
    conflicts=[row['column'] for row in rows if row.get('formula_conflict')]
    if conflicts: warnings.append('Нет единственной основной формулы: '+', '.join(conflicts)+'. Уточните выражения в книге перед импортом.')
    changed=[row['column'] for row in rows if row.get('changed')]
    if changed: warnings.append('Изменились формулы: '+', '.join(changed)+'. Проверьте расчётные выражения.')
    constants=[row['column']+' = '+item['formula'] for row in rows for item in row['variants'] if item.get('constant_value')]
    if constants: warnings.append('Постоянные поправки из числовых столбцов: '+', '.join(constants)+'. Подтвердите их применимость к новым строкам.')
    return {'kind':'bookMapping','title':'Основная книга — параметры и расчёт',
            'note':' '.join(warnings),
            'roles':[{'value':'','label':'Вспомогательная колонка'}]+[{'value':key,'label':value[0]} for key,value in ROLES.items()],
            'rows':[{**{key:row[key] for key in ('column','header','role','unit','kind','recipe')},
                     'variants':[{key:item.get(key) for key in ('id','formula','count','error','constant_value')} for item in row['variants']],
                     'application_owned':row['column'] in owned}
                    for row in rows]}


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
        for index,row in enumerate(rows,start=1):
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
        content='Основная формула — структура с наибольшим числом строк.\n\n'
        for row,role,_,kind in self.fields:
            if kind.get()!='Расчётный' or not row['variants']: continue
            selected=next((item for item in row['variants'] if item['id']==row['recipe']),None)
            content+=f"{role.get()} ({row['column']})\n"
            content+=(selected['formula']+f"\nИспользуется в {selected['count']} строках." if selected else 'Нет единственной основной формулы.')+'\n\n'
        show_text(self,'Расчётные формулы',content)

    def accept(self):
        roles={label:key for key,(label,_) in ROLES.items()};kinds={label:key for key,label in KIND_LABELS.items()}
        rows=[{**old,'role':roles.get(role.get(),''),'unit':unit.get(),'kind':kinds[kind.get()]} for old,role,unit,kind in self.fields]
        try:self.result=confirm(self.layout,self.station,self.unit,rows,save=False)
        except ValueError as error:
            messagebox.showerror('Проверьте основную книгу',str(error),parent=self);return
        self.destroy()
