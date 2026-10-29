"""Только оформление Tkinter: тема и компоновка, без расчётной логики."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk


COLORS = {
    "window": "#13161b", "panel": "#1b1f26", "input": "#15191f",
    "text": "#eef1f6", "muted": "#a3aebe", "accent": "#4278ef",
    "accent_active": "#94b5ff", "selection": "#304b7b",
    "trough": "#13161b", "border": "#303743", "soft": "#252b35",
    "success": "#72d3a6", "disabled": "#8792a4",
}

RESULT_TABS = (
    ("pressure", "Перепады"), ("vna", "ВНА"), ("boundary", "Границы"),
    ("top10", "ТОП-10"), ("delta", "Деградация"), ("rh", "RH"),
    ("economics", "Экономика"),
)


def _button_image(master, color):
    """Небольшое изображение с растяжимым центром для скруглённых кнопок."""
    size, radius = 20, 6
    image = tk.PhotoImage(master=master, width=size, height=size)
    for y in range(size):
        for x in range(size):
            dx = max(radius - x, 0, x - (size - radius - 1))
            dy = max(radius - y, 0, y - (size - radius - 1))
            if dx * dx + dy * dy <= radius * radius:
                image.put(color, (x, y))
    return image


def configure_theme(app):
    app.colors = COLORS.copy()
    app.configure(background=COLORS["window"])
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name, root=app).configure(family="Segoe UI", size=10)
    style = ttk.Style(app)
    style.theme_use("clam")
    c = app.colors
    style.configure(".", font=("Segoe UI", 10), background=c["panel"],
                    foreground=c["text"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"])
    style.configure("TFrame", background=c["panel"])
    style.configure("Window.TFrame", background=c["window"])
    style.configure("TLabel", background=c["panel"], foreground=c["text"])
    style.configure("Muted.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
    style.configure("Heading.TLabel", font=("Segoe UI Semibold", 13))
    style.configure("Title.TLabel", background=c["window"], font=("Segoe UI Semibold", 20))
    style.configure("CompactTitle.TLabel", background=c["window"], font=("Segoe UI Semibold", 14))
    style.configure("Window.TLabel", background=c["window"], foreground=c["muted"],
                    font=("Segoe UI", 9))
    style.configure("Section.TLabel", font=("Segoe UI Semibold", 10))
    style.configure("Brand.TLabel", font=("Segoe UI Semibold", 15))
    style.configure("TSeparator", background=c["border"])
    style.configure("TEntry", fieldbackground=c["input"], foreground=c["text"],
                    insertcolor=c["text"], selectbackground=c["selection"],
                    selectforeground=c["text"], borderwidth=1, padding=(9, 7))
    style.map("TEntry", bordercolor=[("focus", c["accent"])],
              foreground=[("disabled", c["disabled"])])
    style.configure("TCombobox", fieldbackground=c["input"], background=c["soft"],
                    foreground=c["text"], arrowcolor=c["muted"], padding=(9, 7),
                    arrowsize=14, borderwidth=1)
    style.map("TCombobox", foreground=[("disabled", c["disabled"]), ("readonly", c["text"])],
              fieldbackground=[("readonly", c["input"]), ("disabled", c["panel"])],
              selectbackground=[("readonly", c["input"])],
              selectforeground=[("readonly", c["text"])],
              bordercolor=[("focus", c["accent"])])
    app.option_add("*TCombobox*Listbox.background", c["input"])
    app.option_add("*TCombobox*Listbox.foreground", c["text"])
    app.option_add("*TCombobox*Listbox.selectBackground", c["selection"])
    app.option_add("*TCombobox*Listbox.selectForeground", c["text"])
    app.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")

    app._theme_images = []
    for name, normal, hover, pressed, disabled in (
        ("TButton", c["soft"], "#333c49", "#3d485a", "#242a33"),
        ("Primary.TButton", c["accent"], "#588af5", "#3267d8", "#293751"),
        ("Tab.TButton", c["panel"], c["soft"], c["selection"], c["panel"]),
    ):
        images = [_button_image(app, fill) for fill in (normal, hover, pressed, disabled)]
        app._theme_images.extend(images)
        element = f"{name}.rounded"
        style.element_create(element, "image", images[0],
                             ("disabled", images[3]), ("pressed", images[2]),
                             ("selected", images[2]), ("active", images[1]),
                             border=7, sticky="nsew")
        style.layout(name, [(element, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [
                ("Button.focus", {"sticky": "nsew", "children": [
                    ("Button.label", {"sticky": "nsew"})]})]})]})])
        style.configure(name, padding=(12, 9), borderwidth=0, anchor="center",
                        foreground="#ffffff" if name == "Primary.TButton" else c["text"],
                        font=("Segoe UI Semibold", 10) if name == "Primary.TButton"
                        else ("Segoe UI", 10))
        style.map(name, foreground=[("disabled", c["disabled"])])
    style.configure("Tab.TButton", padding=(9, 10), foreground=c["muted"])
    style.map("Tab.TButton", foreground=[("selected", c["text"]), ("active", c["text"])])
    style.configure("TRadiobutton", padding=(5, 7), indicatorbackground=c["input"],
                    indicatorforeground=c["accent"], foreground=c["text"])
    style.map("TRadiobutton", background=[("active", c["panel"])],
              foreground=[("disabled", c["disabled"])],
              indicatorbackground=[("selected", c["accent"])])
    style.configure("TNotebook", background=c["panel"], borderwidth=0, tabmargins=0)
    style.layout("Workspace.TNotebook.Tab", [])
    style.configure("TNotebook.Tab", padding=(10, 8), background=c["soft"])
    style.map("TNotebook.Tab", background=[("selected", c["selection"])])
    style.configure("TProgressbar", troughcolor=c["window"], background=c["accent"],
                    borderwidth=0, lightcolor=c["accent"], darkcolor=c["accent"])
    style.configure("Treeview", background=c["input"], fieldbackground=c["input"],
                    foreground=c["text"], rowheight=30, borderwidth=0)
    style.map("Treeview", background=[("selected", c["selection"])],
              foreground=[("selected", c["text"])])
    style.configure("Treeview.Heading", background=c["soft"], foreground=c["muted"],
                    font=("Segoe UI Semibold", 10), padding=(10, 9), relief="flat")
    style.map("Treeview.Heading", background=[("active", "#333c49")])
    style.configure("TScrollbar", background=c["soft"], troughcolor=c["panel"],
                    borderwidth=0, arrowsize=12, arrowcolor=c["muted"])
    style.map("TScrollbar", background=[("active", "#465166")])
    style.configure("TLabelframe", background=c["panel"], bordercolor=c["border"],
                    borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", foreground=c["muted"], background=c["panel"])


class ScrollableSettings(ttk.Frame):
    """Прокручивается только панель настроек; колесо графиков не затрагивается."""
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=COLORS["panel"],
                                width=290, borderwidth=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.content = ttk.Frame(self.canvas, padding=(18, 18, 12, 18))
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._measure)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(
            self.window, width=event.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<FocusIn>", self._focus, add="+")

    def _measure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _contains(self, widget):
        return str(widget).startswith(str(self) + ".")

    def _wheel(self, event):
        if self._contains(event.widget) and self.content.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

    def _focus(self, event):
        if not self._contains(event.widget) or event.widget is self.canvas:
            return
        self.update_idletasks()
        top = event.widget.winfo_rooty() - self.content.winfo_rooty()
        viewport = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if top < viewport or top + event.widget.winfo_height() > viewport + height:
            self.canvas.yview_moveto(max(0, top - height / 3) / max(1, self.content.winfo_height()))


class ResultNavigation(ttk.Frame):
    """Кнопки выбирают прежние вкладки Notebook; при тесном окне переносятся."""
    def __init__(self, master, notebook, frames):
        super().__init__(master, padding=(8, 8, 8, 6))
        self.notebook, self.frames = notebook, frames
        self.buttons = []
        for key, title in RESULT_TABS:
            button = ttk.Button(self, text=title, style="Tab.TButton",
                                command=lambda key=key: notebook.select(frames[key]))
            self.buttons.append((key, button))
        self.columns = None
        self.bind("<Configure>", self._layout)
        notebook.bind("<<NotebookTabChanged>>", self._select, add="+")
        self._select()

    def _layout(self, event):
        needed = sum(button.winfo_reqwidth() + 2 for _, button in self.buttons)
        columns = 7 if event.width >= needed else 4 if event.width >= 360 else 3
        if columns == self.columns:
            return
        self.columns = columns
        for index in range(7):
            self.columnconfigure(index, weight=1 if index < columns else 0)
        for index, (_, button) in enumerate(self.buttons):
            button.grid(row=index // columns, column=index % columns, sticky="ew", padx=1, pady=1)

    def _select(self, _event=None):
        selected = self.notebook.select()
        for key, button in self.buttons:
            button.state(["selected"] if str(self.frames[key]) == selected else ["!selected"])


def _section(parent, number, title):
    block = ttk.Frame(parent)
    block.pack(fill="x", pady=(20, 0))
    ttk.Label(block, text=f"{number}   {title}", style="Section.TLabel").pack(anchor="w", pady=(0, 12))
    return block


def build_widgets(app):
    """Создаёт только виджеты; command/variable/bind ведут к прежним обработчикам."""
    header = ttk.Frame(app, padding=(22, 14))
    header.pack(fill="x")
    ttk.Label(header, text="ГТУ", style="Brand.TLabel").pack(side="left")
    ttk.Label(header, text="Параметрический расчёт", style="Muted.TLabel").pack(side="left", padx=16)
    ttk.Separator(app).pack(fill="x")

    body = ttk.Frame(app, style="Window.TFrame")
    body.pack(fill="both", expand=True)
    sidebar = ttk.Frame(body, width=316)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    ttk.Separator(body, orient="vertical").pack(side="left", fill="y")

    run_area = ttk.Frame(sidebar, padding=(18, 12, 18, 16))
    run_area.pack(side="bottom", fill="x")
    app.run_button = ttk.Button(run_area, text="Расчет", style="Primary.TButton",
                                command=app.start_calculation, state="disabled")
    app.run_button.pack(fill="x")
    ttk.Label(run_area, text="Периоды подтверждаются перед расчётом",
              style="Muted.TLabel", wraplength=275, justify="center").pack(pady=(8, 0))
    settings = ScrollableSettings(sidebar)
    settings.pack(fill="both", expand=True)
    app.settings_panel = settings
    content = settings.content
    ttk.Label(content, text="Подготовка расчёта", style="Heading.TLabel").pack(anchor="w")
    ttk.Label(content, text="Данные, станция и тарифы", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

    inputs = _section(content, "1", "Исходные данные")
    app.file_label = ttk.Label(inputs, text="Файл не выбран", wraplength=255, justify="left")
    app.file_label.pack(fill="x", pady=(0, 6))
    ttk.Label(inputs, text="Расчётная книга · первый лист «Данные»", style="Muted.TLabel",
              wraplength=255).pack(anchor="w", pady=(0, 10))
    app.choose_button = ttk.Button(inputs, text="Выбрать Excel-файл", command=app.choose_file)
    app.choose_button.pack(fill="x")
    ttk.Label(inputs, text="Теплоэлектроцентраль", style="Muted.TLabel").pack(anchor="w", pady=(16, 6))
    app.station_combo = ttk.Combobox(inputs, textvariable=app.station_var,
                                    values=list(app.stations_by_name), state="readonly")
    app.station_combo.pack(fill="x")
    app.station_combo.bind("<<ComboboxSelected>>", app._on_station_changed)
    app.station_hint = ttk.Label(inputs, text="Выберите ТЭЦ или загрузите файл.",
                                  style="Muted.TLabel", wraplength=255)
    app.station_hint.pack(fill="x", pady=(6, 0))
    app.corrections_button = ttk.Button(inputs, text="Поправки ГТ", command=app.review_corrections)
    app.corrections_button.pack(fill="x",pady=(8,0))

    mode = _section(content, "2", "Режим расчёта")
    app.mode_buttons = []
    for title, value in (("Готовая расчётная книга", "ready"),
                         ("Импорт данных датчиков", "import")):
        button = ttk.Radiobutton(mode, text=title, value=value,
                                  variable=app.calculation_mode, command=app._on_mode_changed)
        button.pack(anchor="w", fill="x")
        app.mode_buttons.append(button)
    imports = ttk.Frame(mode)
    app.import_controls = imports
    app.raw_button = ttk.Button(imports, text="Выбрать выгрузку датчиков", command=app.choose_raw_file,
                                state="disabled")
    app.raw_button.pack(fill="x", pady=(10, 0))
    ttk.Label(imports, text="Лист выгрузки", style="Muted.TLabel").pack(anchor="w", pady=(10, 5))
    app.raw_sheet_combo = ttk.Combobox(imports, textvariable=app.selected_raw_sheet, state="disabled")
    app.raw_sheet_combo.pack(fill="x")
    app.raw_sheet_combo.bind("<<ComboboxSelected>>", app._on_raw_sheet_changed)
    app.mapping_button = ttk.Button(imports, text="Проверить колонки", command=app.review_mapping,
                                    state="disabled")
    app.mapping_button.pack(fill="x", pady=(8, 0))
    app.clear_raw_button = ttk.Button(imports, text="Убрать выгрузку", command=app.clear_raw_file,
                                      state="disabled")
    app.clear_raw_button.pack(fill="x", pady=(6, 0))
    app.raw_label = ttk.Label(imports, text="Выгрузка не выбрана", style="Muted.TLabel", wraplength=255)
    app.raw_label.pack(fill="x", pady=(7, 0))

    tariffs = _section(content, "3", "Тарифы")
    app.tariff_entries = []
    for index, (title, unit, variable) in enumerate((
        ("Газ", "руб/нм³", app.gas_tariff_var),
        ("Электроэнергия", "руб/МВт·ч", app.electricity_tariff_var),
        ("Себестоимость ЭЭ", "руб/МВт·ч", app.electricity_cost_var),
    )):
        row = ttk.Frame(tariffs)
        row.pack(fill="x", pady=(0, 10))
        label = ttk.Frame(row)
        label.pack(side="left", fill="x", expand=True)
        ttk.Label(label, text=title).pack(anchor="w")
        ttk.Label(label, text=unit, style="Muted.TLabel").pack(anchor="w")
        entry = ttk.Entry(row, textvariable=variable, width=10, justify="right")
        entry.pack(side="right", padx=(6, 0))
        app.tariff_entries.append(entry)

    work = ttk.Frame(body, style="Window.TFrame", padding=(22, 20, 22, 12))
    work.pack(side="left", fill="both", expand=True)
    work.columnconfigure(0, weight=1)
    work.rowconfigure(1, weight=1)
    title_row = ttk.Frame(work, style="Window.TFrame")
    title_row.grid(row=0, column=0, sticky="ew", pady=(0, 18))
    title_block = ttk.Frame(title_row, style="Window.TFrame")
    title_block.pack(side="left", fill="x", expand=True)
    heading = ttk.Label(title_block, text="Рабочее пространство", style="Title.TLabel")
    heading.pack(anchor="w")
    ttk.Label(title_block, text="Графики, таблицы и отчёты", style="Window.TLabel").pack(anchor="w", pady=(5, 0))
    export = ttk.Frame(title_row, style="Window.TFrame")
    export.pack(side="right", padx=(12, 0))
    app.excel_button = ttk.Button(export, text="Excel", command=app.generate_excel_report,
                                  state="disabled")
    app.excel_button.pack(side="left", padx=(0, 6))
    app.report_button = ttk.Button(export, text="Word", command=app.generate_word_report,
                                   state="disabled")
    app.report_button.pack(side="left")
    # Короткий заголовок сохраняет место для результатов и экспорта в узком окне.
    def fit_header(event):
        heading.configure(style="CompactTitle.TLabel" if event.width < 700 else "Title.TLabel")
    title_row.bind("<Configure>", fit_header)

    results = ttk.Frame(work)
    results.grid(row=1, column=0, sticky="nsew")
    results.columnconfigure(0, weight=1)
    results.rowconfigure(2, weight=1)
    app.chart_tabs = ttk.Notebook(results, style="Workspace.TNotebook")
    app.tab_frames = {}
    for key, title in RESULT_TABS:
        frame = ttk.Frame(app.chart_tabs)
        app.chart_tabs.add(frame, text=title)
        app.tab_frames[key] = frame
    nav = ResultNavigation(results, app.chart_tabs, app.tab_frames)
    nav.grid(row=0, column=0, sticky="ew")
    ttk.Separator(results).grid(row=1, column=0, sticky="ew")
    app.chart_tabs.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
    app.chart_tabs.enable_traversal()

    journal = ttk.Frame(work, padding=(12, 8))
    journal.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    ttk.Label(journal, text="Журнал расчёта", style="Section.TLabel").pack(side="left")
    app.events_button = ttk.Button(journal, text="События графика (0)", command=app.review_chart_events)
    app.events_button.pack(side="right", padx=(8, 0))
    app.journal_content = ttk.Frame(work, height=110, padding=(10, 0, 8, 8))
    app.journal_content.grid(row=3, column=0, sticky="ew")
    app.journal_content.grid_propagate(False)
    app.journal_content.rowconfigure(0, weight=1)
    app.journal_content.columnconfigure(0, weight=1)
    def toggle_journal():
        shown = bool(app.journal_content.winfo_manager())
        app.journal_content.grid_remove() if shown else app.journal_content.grid()
        toggle.configure(text="Развернуть" if shown else "Свернуть")
    toggle = ttk.Button(journal, text="Свернуть", command=toggle_journal)
    toggle.pack(side="right")
    app.journal_toggle = toggle
    app.log = tk.Text(app.journal_content, wrap="none", state="disabled", relief="flat",
                      borderwidth=0, background=app.colors["input"], foreground=app.colors["text"],
                      insertbackground=app.colors["text"], selectbackground=app.colors["selection"],
                      selectforeground=app.colors["text"], padx=12, pady=10, font=("Consolas", 10))
    app.log.tag_configure("section_heading", font=("Consolas", 10, "bold"),
                          foreground=app.colors["accent_active"])
    app.log.tag_configure("degradation", font=("Consolas", 11, "bold"), foreground="#ffbd70")
    scroll_y = ttk.Scrollbar(app.journal_content, orient="vertical", command=app.log.yview)
    scroll_x = ttk.Scrollbar(app.journal_content, orient="horizontal", command=app.log.xview)
    app.log.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    app.log.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    footer = ttk.Frame(work, style="Window.TFrame")
    footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
    app.status_label = ttk.Label(footer, text="Выберите исходную книгу", style="Window.TLabel")
    app.status_label.pack(side="left")
    app.progress = ttk.Progressbar(footer, mode="indeterminate", length=110)
    app.progress.pack(side="right")
    show_empty_states(app)


def show_empty_states(app):
    for key, title in RESULT_TABS:
        frame = app.tab_frames[key]
        if frame.winfo_children():
            continue
        empty = ttk.Frame(frame, padding=24)
        empty.place(relx=.5, rely=.5, anchor="center", relwidth=.92)
        ttk.Label(empty, text=title, style="Heading.TLabel", anchor="center").pack(fill="x")
        ttk.Label(empty, text="Результаты появятся после расчёта", style="Muted.TLabel",
                  anchor="center", wraplength=300, justify="center").pack(fill="x", pady=(10, 0))


def update_status(app):
    """Только подпись существующего состояния; доступность кнопок решает app.py."""
    if app.calculation_mode.get() == "import":
        app.import_controls.pack(fill="x")
    else:
        app.import_controls.pack_forget()
    if app.calculation_running:
        text = "Расчёт выполняется…"
    elif app.export_running:
        text = "Формирование отчёта…"
    elif app.last_result is not None:
        text = "Результаты готовы"
    elif app.selected_file is None:
        text = "Выберите исходную книгу"
    elif app.station_var.get() not in app.stations_by_name:
        text = "Выберите ТЭЦ"
    else:
        text = "Готово к расчету"
    app.status_label.configure(text=text)
