"""Общие поля паспорта газа и диалог прежней Tkinter-оболочки."""
import tkinter as tk
from tkinter import ttk, messagebox

from gas_passport import COMPONENTS, GasPassport
from ui_theme import ScrollableSettings

FIELDS = (("density_kg_per_nm3", "Плотность", "кг/нм³"),
          ("q_lower_mj_per_nm3", "Qнр (паспорт)", "МДж/нм³"),
          ("carbon_hydrogen_ratio", "C/H", "о.е."))


def passport_fields(passport):
    values = passport.to_dict() if passport is not None else {}
    fields = [{"key": key, "label": label, "unit": unit,
               "value": str(values.get(key, "")).replace(".", ",")} for key, label, unit in FIELDS]
    composition = dict(passport.components) if passport is not None else {}
    for name in dict.fromkeys((*COMPONENTS, *composition)):
        fields.append({"key": f"component:{name}", "label": name,
                       "unit": "молярная доля, 0..1",
                       "value": str(composition.get(name, "")).replace(".", ",")})
    return fields


def passport_from_fields(values, station_id, unit):
    composition = {key.split(":", 1)[1]: value for key, value in values.items()
                   if key.startswith("component:") and str(value).strip()}
    return GasPassport.from_dict({"station_id": station_id, "unit": unit,
                                  **{key: values.get(key, "") for key, _, _ in FIELDS},
                                  "components": composition})


class GasPassportDialog(tk.Toplevel):
    def __init__(self, parent, passport, station_id, unit, station_name):
        super().__init__(parent)
        self.result = None
        self.station_id, self.unit = station_id, unit
        self.title(f"Паспорт газа — {station_name} ГТ-{unit}")
        self.transient(parent)
        height = min(720, self.winfo_screenheight() - 100)
        self.geometry(f"600x{height}")
        self.minsize(440, 350)
        ttk.Label(self, text=f"{station_name} · ГТ-{unit}", font=("Segoe UI", 13, "bold")).pack(padx=18, pady=12)
        ttk.Label(self, text="Точка и запятая допустимы. Состав вводится в долях 0..1.").pack(padx=18)
        content = ScrollableSettings(self)
        content.pack(fill="both", expand=True)
        self.values = {}
        for i, field in enumerate(passport_fields(passport)):
            ttk.Label(content.content, text=f"{field['label']}, {field['unit']}").grid(row=i, column=0, sticky="w", pady=5)
            variable = tk.StringVar(value=field["value"])
            self.values[field["key"]] = variable
            ttk.Entry(content.content, textvariable=variable).grid(row=i, column=1, sticky="ew", padx=10)
        content.content.columnconfigure(1, weight=1)
        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Сохранить", command=self.accept).pack(side="right", padx=8)
        self.grab_set()

    def accept(self):
        try:
            self.result = passport_from_fields({key: value.get() for key, value in self.values.items()},
                                               self.station_id, self.unit)
        except ValueError as error:
            messagebox.showerror("Паспорт газа", str(error), parent=self)
            return
        self.destroy()
