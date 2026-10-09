# -*- coding: utf-8 -*-
"""Графическое окно для расчётов ГТУ."""
from __future__ import annotations

import contextlib
import queue
import threading
import traceback
from pathlib import Path

import matplotlib

# Графики строятся в памяти, а затем встраиваются во вкладки Tkinter.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import periods as periods_mod
from data_loader import load_source_data, prepare_rh_data, prepare_vna_data
from RH_raschet import (
    main as run_rh,
    plot_pressure_drops,
    plot_selected_windows,
)
from VNA_full import run_vna
from periods import parse_periods_arg


ROOT = Path(__file__).resolve().parents[1]


class QueueWriter:
    """Перенаправляет print из расчёта в очередь окна."""

    def __init__(self, output_queue: queue.Queue):
        self.output_queue = output_queue

    def write(self, text: str):
        if text:
            self.output_queue.put(("log", text))

    def flush(self):
        pass


class FigureViewer(ttk.Frame):
    """Показывает рисунок в неизменной области с прокруткой и масштабом."""

    def __init__(self, parent, figure, colors):
        super().__init__(parent)
        self.figure = figure
        self.base_size = tuple(figure.get_size_inches())
        self.zoom = 1.0
        self.target_zoom = 1.0
        self.zoom_after = None
        self.zoom_anchor = None

        toolbar = ttk.Frame(self, padding=(5, 3))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Колесо мыши — масштаб").pack(side="left")
        self.zoom_label = ttk.Label(toolbar, text="100 %")
        self.zoom_label.pack(side="right", padx=(8, 2))
        ttk.Button(toolbar, text="100 %", command=self.reset_zoom).pack(side="right")

        area = ttk.Frame(self)
        area.pack(fill="both", expand=True)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)

        self.viewport = tk.Canvas(
            area,
            background=colors["input"],
            highlightthickness=0,
            borderwidth=0,
        )
        self.scroll_y = ttk.Scrollbar(
            area, orient="vertical", command=self.viewport.yview
        )
        self.scroll_x = ttk.Scrollbar(
            area, orient="horizontal", command=self.viewport.xview
        )
        self.viewport.configure(
            xscrollcommand=self.scroll_x.set,
            yscrollcommand=self.scroll_y.set,
        )
        self.viewport.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")

        self.mpl_canvas = FigureCanvasTkAgg(figure, master=self.viewport)
        self.widget = self.mpl_canvas.get_tk_widget()
        self.window_id = self.viewport.create_window(
            (0, 0), window=self.widget, anchor="nw"
        )
        self._resize_figure(1.0)
        self.mpl_canvas.draw()

        for widget in (self.viewport, self.widget):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", self._on_wheel)
            widget.bind("<Button-5>", self._on_wheel)

    def _resize_figure(self, zoom):
        width = max(1, round(self.base_size[0] * self.figure.dpi * zoom))
        height = max(1, round(self.base_size[1] * self.figure.dpi * zoom))
        self.figure.set_size_inches(
            self.base_size[0] * zoom,
            self.base_size[1] * zoom,
            forward=False,
        )
        self.widget.configure(width=width, height=height)
        self.viewport.itemconfigure(self.window_id, width=width, height=height)
        self.viewport.configure(scrollregion=(0, 0, width, height))
        self.zoom = zoom
        self.zoom_label.configure(text=f"{zoom:.0%}")

    def _on_wheel(self, event):
        direction = 1 if getattr(event, "delta", 0) > 0 else -1
        if getattr(event, "num", None) == 4:
            direction = 1
        elif getattr(event, "num", None) == 5:
            direction = -1

        next_zoom = self.target_zoom * (1.15 if direction > 0 else 1 / 1.15)
        self.target_zoom = min(2.5, max(0.5, next_zoom))
        x = event.x + event.widget.winfo_rootx() - self.viewport.winfo_rootx()
        y = event.y + event.widget.winfo_rooty() - self.viewport.winfo_rooty()
        self.zoom_anchor = (
            self.viewport.canvasx(x),
            self.viewport.canvasy(y),
            x,
            y,
        )
        if self.zoom_after is not None:
            self.after_cancel(self.zoom_after)
        self.zoom_after = self.after(80, self._apply_zoom)
        return "break"

    def _apply_zoom(self):
        self.zoom_after = None
        old_zoom = self.zoom
        self._resize_figure(self.target_zoom)
        self.mpl_canvas.draw_idle()
        if self.zoom_anchor is not None:
            content_x, content_y, pointer_x, pointer_y = self.zoom_anchor
            scale = self.zoom / old_zoom
            width = self.base_size[0] * self.figure.dpi * self.zoom
            height = self.base_size[1] * self.figure.dpi * self.zoom
            self.viewport.xview_moveto(max(0, content_x * scale - pointer_x) / width)
            self.viewport.yview_moveto(max(0, content_y * scale - pointer_y) / height)

    def reset_zoom(self):
        self.target_zoom = 1.0
        self.zoom_anchor = None
        if self.zoom_after is not None:
            self.after_cancel(self.zoom_after)
        self._apply_zoom()
        self.viewport.xview_moveto(0)
        self.viewport.yview_moveto(0)


class CalculationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Параметрический расчёт ГТУ")
        self.geometry("1200x800")
        self.minsize(900, 600)

        self._configure_dark_theme()

        self.output_queue: queue.Queue = queue.Queue()
        self.selected_file: Path | None = None
        self.figure_views = []

        self._build_widgets()
        self.after(100, self._poll_output)

    def _configure_dark_theme(self):
        """Настраивает тёмную тему окна, лога и вкладок графиков."""

        self.colors = {
            "window": "#202124",
            "panel": "#292b2f",
            "input": "#17181a",
            "text": "#e8eaed",
            "muted": "#b8bdc7",
            "accent": "#79a7ff",
            "accent_active": "#9bbcff",
            "selection": "#3d5f9e",
            "trough": "#151619",
        }

        self.configure(bg=self.colors["window"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".",
                        background=self.colors["panel"],
                        foreground=self.colors["text"])
        style.configure("TFrame", background=self.colors["panel"])
        style.configure("TLabel",
                        background=self.colors["panel"],
                        foreground=self.colors["text"])
        style.configure("TButton",
                        background="#3a3d43",
                        foreground=self.colors["text"],
                        padding=(10, 6))
        style.map(
            "TButton",
            background=[
                ("active", "#4a4e57"),
                ("disabled", "#303238"),
            ],
            foreground=[("disabled", "#777b85")],
        )
        style.configure("TLabelFrame",
                        background=self.colors["panel"],
                        foreground=self.colors["text"])
        style.configure("TLabelframe.Label",
                        background=self.colors["panel"],
                        foreground=self.colors["text"])
        style.configure("TNotebook",
                        background=self.colors["panel"],
                        borderwidth=0)
        style.configure("TNotebook.Tab",
                        background="#34373d",
                        foreground=self.colors["muted"],
                        padding=(10, 5))
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#4a4f59"), ("active", "#41454d")],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure("TProgressbar",
                        troughcolor=self.colors["trough"],
                        background=self.colors["accent"],
                        bordercolor=self.colors["trough"],
                        lightcolor=self.colors["accent"],
                        darkcolor=self.colors["accent"])
        style.configure(
            "Treeview",
            background=self.colors["input"],
            fieldbackground=self.colors["input"],
            foreground=self.colors["text"],
            rowheight=25,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", self.colors["selection"])],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background="#3a3d43",
            foreground=self.colors["text"],
            padding=(7, 6),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#4a4e57")],
        )

    def _build_widgets(self):
        controls = ttk.Frame(self, padding=10)
        controls.pack(fill="x")

        self.choose_button = ttk.Button(
            controls,
            text="Выбрать Excel-файл",
            command=self.choose_file,
        )
        self.choose_button.pack(side="left")

        self.run_button = ttk.Button(
            controls,
            text="Запустить расчёт",
            command=self.start_calculation,
            state="disabled",
        )
        self.run_button.pack(side="left", padx=(10, 0))

        self.file_label = ttk.Label(
            controls,
            text="Файл не выбран",
            anchor="w",
        )
        self.file_label.pack(side="left", padx=(14, 0), fill="x", expand=True)

        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=160)
        self.progress.pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_frame = ttk.LabelFrame(panes, text="Лог расчёта", padding=5)
        panes.add(log_frame, weight=2)

        self.log = tk.Text(
            log_frame,
            wrap="none",
            state="disabled",
            background=self.colors["input"],
            foreground=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground=self.colors["selection"],
            selectforeground=self.colors["text"],
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=8,
            font=("Consolas", 10),
        )
        self.log.tag_configure(
            "section_heading",
            font=("Consolas", 10, "bold"),
            foreground=self.colors["accent_active"],
        )
        self.log.tag_configure(
            "degradation",
            font=("Consolas", 11, "bold"),
            foreground="#ffbd70",
        )
        log_scroll_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll_y.grid(row=0, column=1, sticky="ns")
        log_scroll_x.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        chart_frame = ttk.LabelFrame(panes, text="Графики и таблицы", padding=5)
        panes.add(chart_frame, weight=3)

        self.chart_tabs = ttk.Notebook(chart_frame)
        self.chart_tabs.pack(fill="both", expand=True)
        self.tab_frames = {}
        for key, title in (
            ("pressure", "Перепады давления"),
            ("vna", "ВНА"),
            ("boundary", "Параметры на границах"),
            ("top10", "TOP-10 ВНА"),
            ("delta", "Дельты по регрессиям"),
            ("rh", "Графики RH"),
        ):
            frame = ttk.Frame(self.chart_tabs)
            self.chart_tabs.add(frame, text=title)
            self.tab_frames[key] = frame

    def choose_file(self):
        file_name = filedialog.askopenfilename(
            title="Выберите книгу с данными",
            initialdir=str(ROOT / "data"),
            filetypes=[
                ("Excel-файлы", "*.xlsx *.xlsm *.xls *.xlsb"),
                ("Все файлы", "*.*"),
            ],
        )
        if not file_name:
            return

        self.selected_file = Path(file_name)
        self.file_label.configure(text=str(self.selected_file))
        self.run_button.configure(state="normal")

    def start_calculation(self):
        if self.selected_file is None:
            return

        self._clear_log()
        self._clear_charts()
        self.choose_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.progress.start(10)

        worker = threading.Thread(
            target=self._calculation_worker,
            args=(self.selected_file,),
            daemon=True,
        )
        worker.start()

    def _calculation_worker(self, file_path: Path):
        writer = QueueWriter(self.output_queue)

        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                print(f"Выбран файл: {file_path}")
                print("Лист: Данные")

                periods_mod.PERIOD_OVERRIDES = []
                source = load_source_data(file_path, "Данные")
                rh_data = prepare_rh_data(source)
                vna_data = prepare_vna_data(source)

                print()
                print("=" * 78)
                print("ПРЕДПРОСМОТР АВТОМАТИЧЕСКОЙ РАЗБИВКИ ПЕРИОДОВ")
                print("=" * 78)
                preview_df, preview_periods, _, _ = run_rh(
                    rh_data,
                    periods_only=True,
                    show_plots=False,
                )
                preview_figure = plot_pressure_drops(
                    preview_df,
                    preview_periods,
                    show=False,
                )
                if preview_figure is not None:
                    self.output_queue.put(("pressure_figure", preview_figure))

                period_choice = {
                    "event": threading.Event(),
                    "overrides": None,
                    "periods_df": preview_periods,
                }
                self.output_queue.put(("period_choice", period_choice))
                period_choice["event"].wait()

                periods_mod.PERIOD_OVERRIDES = period_choice["overrides"] or []
                if periods_mod.PERIOD_OVERRIDES:
                    print()
                    print(
                        f"Используем {len(periods_mod.PERIOD_OVERRIDES)} "
                        "периодов, заданных вручную."
                    )
                    _, corrected_periods = periods_mod.build_periods(rh_data)
                    corrected_figure = plot_pressure_drops(
                        rh_data,
                        corrected_periods,
                        show=False,
                    )
                    if corrected_figure is not None:
                        self.output_queue.put(("pressure_figure", corrected_figure))
                else:
                    print()
                    print("Используем автоматическую разбивку периодов.")

                print()
                print("=" * 78)
                print("РАСЧЁТ ВНА")
                print("=" * 78)
                vna_df, vna_periods, vna_results, vna_figures = run_vna(
                    data=vna_data,
                    show_plots=False,
                )
                vna_figure = self._build_vna_overview(vna_figures, vna_periods)
                for figure in vna_figures:
                    plt.close(figure)

                print()
                print("=" * 78)
                print("РАСЧЁТ РАСХОДНОЙ ХАРАКТЕРИСТИКИ")
                print("=" * 78)
                output_tables = {}
                rh_df, rh_periods, rh_results, _ = run_rh(
                    rh_data,
                    periods_only=False,
                    show_plots=False,
                    vna_data=vna_df,
                    output_tables=output_tables,
                )

                pressure_figure = plot_pressure_drops(
                    rh_df,
                    rh_periods,
                    show=False,
                )

                windows_figure = plot_selected_windows(
                    rh_df,
                    rh_results,
                    show=False,
                )
                self.output_queue.put(("results", {
                    "vna_figure": vna_figure,
                    "vna_periods": vna_periods,
                    "vna_results": vna_results,
                    "pressure_figure": pressure_figure,
                    "boundary_table": output_tables.get("boundary"),
                    "delta_table": output_tables.get("delta"),
                    "rh_figure": windows_figure,
                }))
                print()
                print("=" * 78)
                print("ВСЁ ГОТОВО: расчёт завершён.")

        except Exception:
            self.output_queue.put(("error", traceback.format_exc()))
        finally:
            self.output_queue.put(("finished", None))

    def _poll_output(self):
        try:
            while True:
                kind, value = self.output_queue.get_nowait()
                if kind == "log":
                    self._append_log(value)
                elif kind == "pressure_figure":
                    self._show_figure("pressure", value)
                    self.chart_tabs.select(self.tab_frames["pressure"])
                    self.update_idletasks()
                elif kind == "period_choice":
                    self._show_period_choice(value)
                elif kind == "results":
                    self._show_results(value)
                elif kind == "error":
                    self._append_log("\nОШИБКА:\n" + value)
                elif kind == "finished":
                    self.progress.stop()
                    self.choose_button.configure(state="normal")
                    self.run_button.configure(
                        state="normal" if self.selected_file else "disabled"
                    )
        except queue.Empty:
            pass

        self.after(100, self._poll_output)

    def _append_log(self, text: str):
        self.log.configure(state="normal")
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if stripped == "ДЕГРАДАЦИЯ":
                tag = "degradation"
            elif stripped.startswith("Параметры на границах периодов"):
                tag = "section_heading"
            else:
                tag = None
            if tag is None:
                self.log.insert("end", line)
            else:
                self.log.insert("end", line, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _periods_text(periods_df) -> str:
        if periods_df is None or periods_df.empty:
            return ""

        return "\n".join(
            f"{row.date_start:%d-%m-%Y %H:%M};"
            f"{row.date_end:%d-%m-%Y %H:%M}"
            for row in periods_df.itertuples(index=False)
        )

    def _show_period_choice(self, request):
        """Показывает пользователю авторазбивку и даёт заменить даты."""

        dialog = tk.Toplevel(self)
        dialog.title("Проверка периодов")
        dialog.geometry("720x470")
        dialog.minsize(620, 380)
        dialog.configure(bg=self.colors["window"])
        dialog.transient(self)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=(
                "Проверьте автоматическую разбивку. Оставьте даты без изменений "
                "или отредактируйте их вручную."
            ),
            wraplength=670,
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            frame,
            text="Одна строка — один период: дата начала;дата конца",
        ).pack(anchor="w")

        text_box = tk.Text(
            frame,
            wrap="none",
            height=14,
            background=self.colors["input"],
            foreground=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground=self.colors["selection"],
            selectforeground=self.colors["text"],
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=8,
            font=("Consolas", 10),
        )
        text_box.pack(fill="both", expand=True, pady=(5, 10))
        text_box.insert("1.0", self._periods_text(request["periods_df"]))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def use_auto():
            request["overrides"] = None
            request["event"].set()
            dialog.destroy()

        def apply_manual():
            lines = [line.strip() for line in text_box.get("1.0", "end").splitlines()]
            lines = [line for line in lines if line]
            if not lines:
                messagebox.showerror(
                    "Периоды не заданы",
                    "Введите хотя бы один период или выберите автоматическую разбивку.",
                    parent=dialog,
                )
                return

            try:
                overrides = parse_periods_arg("|".join(lines))
            except ValueError as error:
                messagebox.showerror("Ошибка формата дат", str(error), parent=dialog)
                return

            request["overrides"] = overrides
            request["event"].set()
            dialog.destroy()

        ttk.Button(
            buttons,
            text="Использовать автоматическую разбивку",
            command=use_auto,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Применить свои периоды",
            command=apply_manual,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", use_auto)
        dialog.grab_set()
        text_box.focus_set()
        self.wait_window(dialog)

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _clear_charts(self):
        for viewer in self.figure_views:
            plt.close(viewer.figure)
            viewer.destroy()
        self.figure_views.clear()
        for frame in self.tab_frames.values():
            for child in frame.winfo_children():
                child.destroy()

    def _clear_tab(self, key):
        frame = self.tab_frames[key]
        for child in frame.winfo_children():
            if isinstance(child, FigureViewer):
                plt.close(child.figure)
                if child in self.figure_views:
                    self.figure_views.remove(child)
            child.destroy()
        return frame

    def _show_figure(self, key, figure):
        if figure is None:
            return
        frame = self._clear_tab(key)
        viewer = FigureViewer(frame, figure, self.colors)
        viewer.pack(fill="both", expand=True)
        self.figure_views.append(viewer)

    @staticmethod
    def _format_cell(value):
        if value is None or pd.isna(value):
            return "—"
        if isinstance(value, pd.Timestamp):
            return value.strftime("%d-%m-%Y %H:%M")
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    def _show_table(self, key, table):
        frame = self._clear_tab(key)
        if table is None or table.empty:
            ttk.Label(frame, text="Нет данных для отображения").pack(
                anchor="center", expand=True
            )
            return

        table = table.copy()
        columns = [str(column) for column in table.columns]
        holder = ttk.Frame(frame, padding=6)
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            holder,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        scroll_y = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=max(110, len(column) * 9), minwidth=80)

        for row in table.itertuples(index=False, name=None):
            tree.insert("", "end", values=[self._format_cell(value) for value in row])

    def _show_top10_tables(self, results):
        frame = self._clear_tab("top10")
        if not results:
            ttk.Label(frame, text="Нет таблиц TOP-10 для отображения").pack(
                anchor="center", expand=True
            )
            return

        outer = ttk.Frame(frame)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            outer,
            background=self.colors["panel"],
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=8)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        def update_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def match_width(event):
            canvas.itemconfigure(content_window, width=max(event.width, content.winfo_reqwidth()))

        content.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", match_width)

        for index, table in enumerate(results, start=1):
            table = table.drop(columns=["share_percent"], errors="ignore").copy()
            table.insert(3, "│₁", "│")
            table.insert(table.columns.get_loc("eta_1") + 1, "║", "║")
            table.insert(table.columns.get_loc("eta_2") + 1, "│₂", "│")
            ttk.Label(
                content,
                text=f"ПЕРИОД {index}: TOP-10 ИНТЕРВАЛОВ VNA",
            ).pack(anchor="w", pady=(8, 4))
            table_frame = ttk.Frame(content)
            table_frame.pack(fill="both", expand=True)
            self._show_table_in_frame(table_frame, table)

    def _show_table_in_frame(self, frame, table):
        if table is None or table.empty:
            ttk.Label(frame, text="Нет данных").pack(anchor="w")
            return
        columns = [str(column) for column in table.columns]
        tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            height=min(max(len(table) + 1, 3), 12),
        )
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=max(110, len(column) * 9), minwidth=80)
        for row in table.itertuples(index=False, name=None):
            tree.insert("", "end", values=[self._format_cell(value) for value in row])

    @staticmethod
    def _build_vna_overview(figures, periods_df):
        if not figures:
            return None

        rows = len(figures)
        overview, axes = plt.subplots(
            rows,
            1,
            figsize=(14, max(4.5, 4.5 * rows)),
            squeeze=False,
        )
        for index, source_figure in enumerate(figures):
            source_canvas = FigureCanvasAgg(source_figure)
            source_canvas.draw()
            image = np.asarray(source_canvas.buffer_rgba())
            ax = axes[index, 0]
            ax.imshow(image)
            ax.axis("off")
            if periods_df is not None and index < len(periods_df):
                period_number = int(periods_df.iloc[index]["period"])
                ax.set_title(f"ВНА — период {period_number}", fontsize=11)
        overview.subplots_adjust(hspace=0.18, top=0.98, bottom=0.02)
        return overview

    def _show_results(self, results):
        self._show_figure("pressure", results.get("pressure_figure"))
        self._show_figure("vna", results.get("vna_figure"))
        self._show_table("boundary", results.get("boundary_table"))
        self._show_top10_tables(results.get("vna_results", []))
        self._show_table("delta", results.get("delta_table"))
        self._show_figure("rh", results.get("rh_figure"))


def main():
    app = CalculationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
