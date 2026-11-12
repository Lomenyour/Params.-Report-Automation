"""Редактор именованных коэффициентов: общий контракт Qt и Tkinter."""
import tkinter as tk
from tkinter import ttk, messagebox

from correction_profiles import GROUPS, CorrectionProfile
from ui_theme import ScrollableSettings


def correction_groups(profile):
    values = profile.values if profile else {}
    return [{"title": group.title, "formula": group.formula, "fields": [
        {"key": field.key, "label": field.label, "hint": f"Старый шаблон СызТЭЦ: {field.source_cell}",
         "value": str(values.get(field.key, "")).replace(".", ",")}
        for field in group.fields]} for group in GROUPS]


def profile_from_fields(values, station_id, unit, previous=None):
    return CorrectionProfile.from_dict({"station_id": station_id, "unit": unit,
        "source": previous.source if previous else "Ручной ввод", "coefficients": values})


class CorrectionDialog(tk.Toplevel):
    def __init__(self, parent, profile, station_id, unit, station_name):
        super().__init__(parent)
        self.result = None
        self.profile, self.station_id, self.unit = profile, station_id, unit
        self.title(f"Поправки — {station_name} ГТ-{unit}")
        self.transient(parent)
        self.geometry(f"760x{min(760, self.winfo_screenheight()-100)}")
        self.minsize(500,350)
        ttk.Label(self, text=f"{station_name} · ГТ-{unit} — 63 коэффициента", font=("Segoe UI",13,"bold")).pack(padx=15,pady=12)
        content = ScrollableSettings(self)
        content.pack(fill="both",expand=True)
        self.values = {}
        for group in correction_groups(profile):
            frame = ttk.LabelFrame(content.content, text=group["title"], padding=10)
            frame.pack(fill="x",pady=8)
            ttk.Label(frame,text=group["formula"],wraplength=630).grid(row=0,column=0,columnspan=3,sticky="w",pady=5)
            for i,field in enumerate(group["fields"],start=1):
                ttk.Label(frame,text=field["label"]).grid(row=i,column=0,sticky="w")
                value = tk.StringVar(value=field["value"])
                self.values[field["key"]] = value
                ttk.Entry(frame,textvariable=value,width=27).grid(row=i,column=1,padx=8,pady=3)
                ttk.Label(frame,text=field["hint"]).grid(row=i,column=2,sticky="w")
        actions = ttk.Frame(self,padding=12)
        actions.pack(fill="x")
        ttk.Button(actions,text="Отмена",command=self.destroy).pack(side="right")
        ttk.Button(actions,text="Сохранить",command=self.accept).pack(side="right",padx=8)
        self.grab_set()

    def accept(self):
        try:
            self.result = profile_from_fields({key:value.get() for key,value in self.values.items()},
                                              self.station_id,self.unit,self.profile)
        except ValueError as error:
            messagebox.showerror("Поправки",str(error),parent=self)
            return
        self.destroy()
