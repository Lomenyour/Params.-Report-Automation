"""Workbook mapping dialog; the same validated model is used by Tk and Qt."""
import tkinter as tk
from tkinter import ttk, messagebox
from workbook_profile import ROLES, confirm


def dialog_payload(layout, rows):
    warnings=[]
    if layout.formula_error: warnings.append(layout.formula_error)
    warnings.append('При импорте паспорт газа задаёт C/H, Qнр и плотность; в распознанном переводе массового расхода в нормальный объём плотность берётся из паспорта.')
    for row in rows:
        if row.get('changed'):
            warnings.append(f"{row['column']}: прежняя расчётная зависимость изменилась; подтвердите новую.")
        if len(row['variants'])>1:
            warnings.append(f"{row['column']}: несколько вариантов формулы; проверьте выбранную зависимость.")
    return {'kind':'bookMapping','title':'Основная книга — параметры и расчёт',
            'note':' '.join(warnings),
            'roles':[{'value':'','label':'Вспомогательная колонка'}]+[{'value':k,'label':v[0]} for k,v in ROLES.items()],
            'rows':[{**{k:r[k] for k in ('column','header','role','unit','kind','recipe')},'unit_inferred':r.get('unit_inferred',False),
                     'variants':[{k:v.get(k) for k in ('id','formula','count','error')} for v in r['variants']]}
                    for r in rows]}


class BookMappingDialog(tk.Toplevel):
    def __init__(self,parent,layout,rows,station,unit):
        super().__init__(parent)
        self.result=None; self.layout=layout; self.rows=rows; self.station=station; self.unit=unit
        self.title('Основная книга — параметры и расчёт'); self.geometry('1100x700')
        self.minsize(800,500); self.transient(parent)
        canvas=tk.Canvas(self,highlightthickness=0); scroll=ttk.Scrollbar(self,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y'); canvas.pack(fill='both',expand=True); canvas.configure(yscrollcommand=scroll.set)
        body=ttk.Frame(canvas,padding=12); anchor=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(anchor,width=e.width))
        ttk.Label(body,text=dialog_payload(layout,rows)['note'],wraplength=950).grid(row=0,column=0,columnspan=5,sticky='w')
        self.fields=[]; roles=['Вспомогательная колонка']+[label for label,_ in ROLES.values()]
        for index,row in enumerate(rows,start=1):
            ttk.Label(body,text=f"{row['column']} — {row['header']}",wraplength=230).grid(row=index,column=0,sticky='w',pady=3)
            role=tk.StringVar(value=ROLES[row['role']][0] if row['role'] else roles[0]); unit_var=tk.StringVar(value=row['unit'])
            kind=tk.StringVar(value='Расчётный' if row['kind']=='computed' else 'Измеренный')
            recipe=tk.StringVar(value=row['recipe'])
            ttk.Combobox(body,textvariable=role,values=roles,state='readonly',height=12,width=38).grid(row=index,column=1,sticky='ew')
            ttk.Entry(body,textvariable=unit_var,width=14).grid(row=index,column=2)
            ttk.Combobox(body,textvariable=kind,values=['Измеренный','Расчётный'],state='readonly',width=14).grid(row=index,column=3)
            variants=row['variants']; labels={v['id']:f"{v['count']} строк: {v['formula']}" for v in variants}
            selected=tk.StringVar(value=labels.get(row['recipe'],''))
            ttk.Combobox(body,textvariable=selected,values=list(labels.values()),state='readonly',width=40).grid(row=index,column=4,sticky='ew')
            self.fields.append((row,role,unit_var,kind,selected,labels))
        actions=ttk.Frame(self,padding=12); actions.pack(fill='x')
        ttk.Button(actions,text='Отмена',command=self.destroy).pack(side='right')
        ttk.Button(actions,text='Подтвердить книгу',command=self.accept).pack(side='right',padx=8)
        self.grab_set()

    def accept(self):
        roles={label:key for key,(label,_) in ROLES.items()}
        rows=[{**old,'role':roles.get(role.get(),''),'unit':unit.get(),
               'kind':'computed' if kind.get()=='Расчётный' else 'measured',
               'recipe':next((key for key,value in labels.items() if value==choice.get()),'')}
              for old,role,unit,kind,choice,labels in self.fields]
        try: self.result=confirm(self.layout,self.station,self.unit,rows,save=False)
        except ValueError as error:
            messagebox.showerror('Проверьте основную книгу',str(error),parent=self); return
        self.destroy()
