"""Общие поля паспорта газа и диалог прежней Tkinter-оболочки."""
import tkinter as tk
from tkinter import ttk, messagebox

from gas_passport import COMPONENTS, GasPassport, GasPassportHistory, passport_entries
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


def history_rows(passport):
    return [{"fields": passport_fields(entry), "valid_from": entry.valid_from,
             "valid_until": entry.valid_until} for entry in passport_entries(passport)] if passport else [
                 {"fields": passport_fields(None), "valid_from": "", "valid_until": ""}]


def history_from_rows(rows, station_id, unit):
    entries = []
    for row in rows:
        value = passport_from_fields(row.get("values", {}), station_id, unit).to_dict()
        value.update(valid_from=row.get("valid_from", ""), valid_until=row.get("valid_until", ""))
        entries.append(value)
    if len(entries) == 1 and not entries[0]["valid_from"] and not entries[0]["valid_until"]:
        return GasPassport.from_dict(entries[0], station_id, unit)
    return GasPassportHistory.from_dict({"station_id": station_id, "unit": unit, "entries": entries}, station_id, unit)


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
        ttk.Label(self, text="Один паспорт без дат — весь диапазон. Окончание срока не включается.").pack(padx=12)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.entries = []
        for row in history_rows(passport):
            self.add_entry(row)
        ttk.Button(self, text="+ Добавить паспорт", command=self.add_entry).pack(anchor="w", padx=12, pady=5)
        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Сохранить", command=self.accept).pack(side="right", padx=8)
        self.grab_set()

    def accept(self):
        try:
            self.result = history_from_rows([
                {"values": {key: value.get() for key, value in values.items()},
                 "valid_from": start.get(), "valid_until": end.get()}
                for _, values, start, end in self.entries], self.station_id, self.unit)
        except ValueError as error:
            messagebox.showerror("Паспорт газа", str(error), parent=self)
            return
        self.destroy()

    def add_entry(self, row=None):
        row = row or {"fields": passport_fields(None), "valid_from": "", "valid_until": ""}
        content = ScrollableSettings(self.notebook)
        self.notebook.add(content, text=f"Паспорт {len(self.entries)+1}")
        values = {}
        start, end = tk.StringVar(value=row["valid_from"]), tk.StringVar(value=row["valid_until"])
        for index, (label, variable) in enumerate((("Действует с (ГГГГ-ММ-ДД ЧЧ:ММ)", start), ("До (не включая)", end))):
            ttk.Label(content.content, text=label).grid(row=index, column=0, sticky="w")
            ttk.Entry(content.content, textvariable=variable).grid(row=index, column=1, sticky="ew")
        for index, field in enumerate(row["fields"], 2):
            ttk.Label(content.content, text=f"{field['label']}, {field['unit']}").grid(row=index, column=0, sticky="w", pady=3)
            values[field["key"]] = tk.StringVar(value=field["value"])
            ttk.Entry(content.content, textvariable=values[field["key"]]).grid(row=index, column=1, sticky="ew", padx=10)
        content.content.columnconfigure(1, weight=1)
        record = (content, values, start, end)
        self.entries.append(record)
        def remove():
            if len(self.entries) > 1:
                self.entries.remove(record)
                self.notebook.forget(content)
                content.destroy()
        ttk.Button(content.content, text="Удалить паспорт", command=remove).grid(row=100, column=0, pady=8)
