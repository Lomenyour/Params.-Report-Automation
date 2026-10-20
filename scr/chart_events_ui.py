"""Окно ручного ввода событий диаграммы."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from chart_events import ChartEvent, format_chart_events, parse_chart_events


class ChartEventsDialog(tk.Toplevel):
    def __init__(self, master, events: tuple[ChartEvent, ...], book_name: str):
        super().__init__(master)
        self.title("События на графике")
        self.geometry("760x440")
        self.minsize(620, 360)
        self.transient(master)
        self.result: tuple[ChartEvent, ...] | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        instructions = ttk.Frame(self, padding=12)
        instructions.grid(row=0, column=0, sticky="ew")
        ttk.Label(instructions, text=book_name).pack(anchor="w")
        ttk.Label(instructions, text=(
            "Каждая строка: дата; подпись события\n"
            "Например: 01.05.2026; Замена ВЛО\n"
            "Можно указать время: 01.05.2026 12:30; Замена ВЛО"
        )).pack(anchor="w", pady=(8, 0))

        frame = ttk.Frame(self, padding=(12, 0, 12, 0))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.editor = tk.Text(
            frame, wrap="none", font=("Segoe UI", 11),
            background="#ffffff", foreground="#111111", insertbackground="#111111",
            selectbackground="#3d5f9e", selectforeground="#ffffff",
        )
        self.editor.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.editor.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.editor.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.editor.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.editor.insert("1.0", format_chart_events(events))

        buttons = ttk.Frame(self, padding=12)
        buttons.grid(row=2, column=0, sticky="ew")
        ttk.Button(buttons, text="Очистить", command=lambda: self.editor.delete("1.0", "end")).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Применить", command=self._apply).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self._apply())
        self.grab_set()
        self.editor.focus_set()

    def _apply(self):
        try:
            events = parse_chart_events(self.editor.get("1.0", "end-1c"))
        except ValueError as error:
            messagebox.showerror("Проверьте события", str(error), parent=self)
            return
        self.result = events
        self.destroy()
