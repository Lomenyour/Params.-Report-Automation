# -*- coding: utf-8 -*-
"""Графическое окно для расчётов ГТУ."""
from __future__ import annotations

import contextlib
import queue
import re
import threading
import time
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
    calculate_nominal_hours,
    main as run_rh,
    plot_pressure_drops,
    plot_selected_windows,
)
from VNA_full import run_vna
from economics import calculate_economics, print_economics
from data_assembly import (
    SensorMapping,
    apply_economic_columns,
    assemble_sensor_data,
    calculate_data_columns,
    list_source_sheets,
    load_saved_mappings,
    read_calculation_profile,
    save_mappings,
    source_mapping_info,
    suggest_mappings,
    template_columns,
    validate_mappings,
)
from station_profiles import get_station_repository, sensor_target_columns, unit_number
from gas_passport import resolve_passport, save_passport
from gas_passport_ui import GasPassportDialog
from correction_sheet import read_correction_sheet
from correction_profiles import resolve_profile, require_profile, save_profile
from correction_profiles_ui import CorrectionDialog
from periods import parse_periods_arg
from result_export import collect_result_tables, read_data_sheet, save_result_workbook
from pressure_chart import PressureChartData
from chart_events import ChartEvent, load_chart_events, save_chart_events
from chart_events_ui import ChartEventsDialog
from ui_theme import build_widgets, configure_theme, show_empty_states, update_status
from calculation_snapshot import CalculationSnapshot
from reporting import (
    DEFAULT_REPORT_DIR,
    DEFAULT_TEMPLATE,
    build_report_data,
    generate_report,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = next(
    (path for path in (ROOT / "data", ROOT.parent / "data") if path.exists()),
    Path.home() / "Documents",
)


def delta_table_for_display(table):
    """Добавляет в GUI уже рассчитанную сводку, не меняя исходную таблицу."""
    if table is None or table.empty:
        return table
    summary = table.attrs.get("weighted_summary")
    if not summary:
        return table
    footer = {column: np.nan for column in table.columns}
    footer.update({
        "Период": "Средневзвешенное (снижение N, рост b)",
        "ΔNприв": summary["delta_n"],
        "ΔNприв, %": summary["delta_n_percent"],
        "Δbприв": summary["delta_b"],
        "Δbприв, %": summary["delta_b_percent"],
    })
    return pd.concat([table, pd.DataFrame([footer])], ignore_index=True)


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


class MappingDialog(tk.Toplevel):
    """Проверка и ручная правка соответствий каналов перед импортом."""

    def __init__(self, parent, suggestions: list[SensorMapping],
                 target_headers: dict[str, str | None],
                 source_headers: list[str], verified_duplicates: set[str],
                 station_id: str):
        super().__init__(parent)
        self.title("Соответствие каналов датчиков")
        self.geometry("960x640")
        self.minsize(760, 480)
        self.configure(background=parent.colors["panel"])
        self.transient(parent)
        self.result: list[SensorMapping] | None = None
        self._rows = []
        self._target_headers = target_headers
        self._source_headers = source_headers
        self._verified_duplicates = verified_duplicates
        self._allowed_targets = sensor_target_columns(station_id, parent.station_repository)

        ttk.Label(
            self,
            text=("Проверьте каждый канал, колонку листа «Данные» и коэффициент "
                  "перевода единиц. Колонку можно ввести вручную по букве."),
            wraplength=900,
        ).pack(fill="x", padx=12, pady=(12, 8))
        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True, padx=12)
        canvas = tk.Canvas(
            holder, highlightthickness=0, background=parent.colors["panel"]
        )
        scroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        table = ttk.Frame(canvas)
        table.bind("<Configure>", lambda _event: canvas.configure(
            scrollregion=canvas.bbox("all")
        ))
        table_window = canvas.create_window((0, 0), window=table, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(table_window, width=event.width),
        )
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        ttk.Label(table, text="Канал выгрузки").grid(row=0, column=0, sticky="w")
        ttk.Label(table, text="Колонка «Данные»").grid(row=0, column=1, sticky="w")
        ttk.Label(table, text="Коэффициент").grid(row=0, column=2, sticky="w")
        choices = [
            f"{column} — {header}" for column, header in target_headers.items()
            if header and column in self._allowed_targets
        ]
        for index, suggestion in enumerate(suggestions, start=1):
            target = suggestion.target
            header = target_headers.get(target)
            initial = f"{target} — {header}" if target and header else target
            target_var = tk.StringVar(value=initial)
            factor_var = tk.StringVar(value=f"{suggestion.factor:.10g}")
            ttk.Label(table, text=suggestion.source).grid(
                row=index, column=0, sticky="ew", pady=3
            )
            ttk.Combobox(
                table, textvariable=target_var, values=choices, width=1
            ).grid(row=index, column=1, sticky="ew", padx=(8, 8), pady=3)
            ttk.Entry(table, textvariable=factor_var, width=1).grid(
                row=index, column=2, sticky="ew", pady=3
            )
            self._rows.append((suggestion.source, target_var, factor_var))
        table.columnconfigure(0, weight=2, minsize=180)
        table.columnconfigure(1, weight=4, minsize=300)
        table.columnconfigure(2, weight=1, minsize=130)

        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Применить", command=self._accept).pack(
            side="right", padx=(0, 8)
        )
        self.grab_set()
        self.focus_set()

    def _accept(self):
        mappings = []
        try:
            for source, target_var, factor_var in self._rows:
                text = target_var.get().strip().upper()
                match = re.match(r"^([A-Z]{1,3})(?:\s|$)", text)
                target = match.group(1) if match else ""
                factor = float(factor_var.get().strip().replace(",", "."))
                mappings.append(SensorMapping(source, target, factor))
            validate_mappings(
                mappings, self._source_headers,
                verified_duplicates=self._verified_duplicates,
                target_headers=self._target_headers,
                allowed_targets=self._allowed_targets,
            )
        except ValueError as error:
            messagebox.showerror("Проверьте соответствия", str(error), parent=self)
            return
        self.result = mappings
        self.destroy()


class CalculationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Параметрический расчёт ГТУ")
        self.geometry("1200x800")
        self.minsize(900, 600)

        self._configure_dark_theme()

        self.output_queue: queue.Queue = queue.Queue()
        self.selected_file: Path | None = None
        self.selected_raw_file: Path | None = None
        self.calculation_mode = tk.StringVar(value="ready")
        self.calculation_running = False
        self.export_running = False
        self.has_calculation_run = False
        self.chart_events: tuple[ChartEvent, ...] = ()
        self.selected_raw_sheet = tk.StringVar(value="")
        self.sensor_mappings: list[SensorMapping] | None = None
        self.mapping_sheet: str | None = None
        self.figure_views = []
        self.last_result: CalculationSnapshot | None = None
        self.station_repository = get_station_repository()
        self.stations_by_name = {
            station.name: station for station in self.station_repository.list_stations()
        }
        self.station_var = tk.StringVar(value="")
        self.station_manually_selected = False
        self.gas_tariff_var = tk.StringVar(value="0")
        self.electricity_tariff_var = tk.StringVar(value="0")
        self.electricity_cost_var = tk.StringVar(value="0")

        self._build_widgets()
        self._update_input_controls()
        for variable in (self.gas_tariff_var, self.electricity_tariff_var,
                         self.electricity_cost_var):
            variable.trace_add("write", self._invalidate_results)
        self.after(100, self._poll_output)

    def _configure_dark_theme(self):
        configure_theme(self)

    def _build_widgets(self):
        build_widgets(self)

    def _invalidate_results(self, *_args):
        self.last_result = None
        self._update_input_controls()
        self._clear_charts()

    def _update_input_controls(self):
        idle = not (self.calculation_running or self.export_running)
        importing = self.calculation_mode.get() == "import"
        has_book = self.selected_file is not None
        has_raw = self.selected_raw_file is not None
        has_station = self.station_var.get() in self.stations_by_name
        self.station_combo.configure(state="readonly" if idle else "disabled")
        self.events_button.configure(
            state="normal" if idle and has_book else "disabled",
            text=f"События графика ({len(self.chart_events)})",
        )
        self.choose_button.configure(state="normal" if idle else "disabled")
        if hasattr(self, "gas_passport_button"):
            self.gas_passport_button.configure(state="normal" if idle and has_book and has_station else "disabled")
        if hasattr(self, "corrections_button"):
            self.corrections_button.configure(state="normal" if idle and has_book and has_station else "disabled")
        for button in self.mode_buttons:
            button.configure(state="normal" if idle else "disabled")
        for entry in self.tariff_entries:
            entry.configure(state="normal" if idle else "disabled")
        self.raw_button.configure(state="normal" if idle and importing and has_book else "disabled")
        raw_ready = idle and importing and has_book and has_raw
        self.mapping_button.configure(state="normal" if raw_ready and has_station else "disabled")
        self.clear_raw_button.configure(state="normal" if raw_ready else "disabled")
        self.raw_sheet_combo.configure(state="readonly" if raw_ready else "disabled")
        can_run = idle and has_book and has_station and (
            not importing or (has_raw and bool(self.selected_raw_sheet.get()))
        )
        self.run_button.configure(
            state="normal" if can_run else "disabled",
            text="Перерасчет" if self.has_calculation_run else "Расчет",
        )
        export_state = "normal" if idle and self.last_result is not None else "disabled"
        self.excel_button.configure(state=export_state)
        self.report_button.configure(state=export_state)
        self.raw_label.configure(text=(
            "Выгрузка не используется в этом режиме" if not importing
            else str(self.selected_raw_file) if has_raw else "Выгрузка не выбрана"
        ))
        update_status(self)

    def _apply_station(self, station, *, automatic: bool):
        """Меняет профиль, сбрасывает назначения датчиков и старый результат."""
        self.station_var.set(station.name if station else "")
        self.station_manually_selected = not automatic
        self._clear_mapping()
        if station is not None:
            tariffs = self.station_repository.get_tariffs(station.id)
            for variable, value in (
                (self.gas_tariff_var, tariffs.gas_rub_per_nm3),
                (self.electricity_tariff_var, tariffs.electricity_rub_per_mwh),
                (self.electricity_cost_var, tariffs.electricity_cost_rub_per_mwh),
            ):
                variable.set(f"{value:g}".replace(".", ","))
            self.station_hint.configure(text=(
                "Определена по имени файла; можно изменить."
                if automatic else "Выбрана вручную. Тарифы можно изменить."
            ))
        else:
            for variable in (self.gas_tariff_var, self.electricity_tariff_var,
                             self.electricity_cost_var):
                variable.set("0")
            self.station_hint.configure(text="ТЭЦ не распознана. Выберите её из списка.")
        self._invalidate_results()

    def _on_station_changed(self, _event=None):
        self._apply_station(self.stations_by_name.get(self.station_var.get()), automatic=False)

    def review_corrections(self):
        if self.calculation_running or self.export_running or self.selected_file is None:
            return
        station = self.stations_by_name.get(self.station_var.get())
        turbine = unit_number(self.selected_file)
        if station is None or turbine is None:
            messagebox.showerror("Поправки", "Выберите ТЭЦ; имя книги должно содержать номер ГТ.", parent=self)
            return
        try:
            profile = resolve_profile(self.selected_file, station.id, turbine)
            dialog = CorrectionDialog(self, profile, station.id, turbine, station.name)
            self.wait_window(dialog)
            if dialog.result is None:
                return
            saved = save_profile(dialog.result)
            self._invalidate_results()
            self._append_log(f"Поправки сохранены: {station.name} ГТ-{turbine}, версия {saved.revision}. Для применения выполните перерасчёт.\n")
        except (ValueError, OSError) as error:
            messagebox.showerror("Поправки", str(error), parent=self)

    def review_gas_passport(self):
        if self.calculation_running or self.export_running or self.selected_file is None:
            return
        station = self.stations_by_name.get(self.station_var.get())
        turbine = unit_number(self.selected_file)
        if station is None or turbine is None:
            messagebox.showerror("Паспорт газа", "Выберите ТЭЦ; имя книги должно содержать номер ГТ, например ГТ-11.", parent=self)
            return
        try:
            passport = resolve_passport(self.selected_file, station.id, turbine)
            dialog = GasPassportDialog(self, passport, station.id, turbine, station.name)
            self.wait_window(dialog)
            if dialog.result is None:
                return
            saved = save_passport(dialog.result)
            self._invalidate_results()
            self._append_log(f"Паспорт газа сохранён: {station.name} ГТ-{turbine}. Для применения выполните перерасчёт.\n")
            if saved.composition_warning:
                messagebox.showwarning("Состав газа", saved.composition_warning, parent=self)
        except (ValueError, OSError) as error:
            messagebox.showerror("Паспорт газа", str(error), parent=self)

    def _on_mode_changed(self):
        self._invalidate_results()
        self._update_input_controls()

    def _on_raw_sheet_changed(self, _event=None):
        self._clear_mapping()
        self._invalidate_results()
        self._update_input_controls()

    def clear_raw_file(self):
        self.selected_raw_file = None
        self.selected_raw_sheet.set("")
        self.raw_sheet_combo.configure(values=())
        self._clear_mapping()
        self._invalidate_results()
        self._update_input_controls()

    def choose_file(self):
        file_name = filedialog.askopenfilename(
            title="Выберите книгу с данными",
            initialdir=str(DATA_DIR),
            filetypes=[
                ("Excel-файлы", "*.xlsx *.xlsm *.xls *.xlsb"),
                ("Все файлы", "*.*"),
            ],
        )
        if not file_name:
            return

        self.selected_file = Path(file_name)
        self._apply_station(
            self.station_repository.detect_station(self.selected_file), automatic=True,
        )
        self.has_calculation_run = False
        try:
            self.chart_events = load_chart_events(self.selected_file)
        except (OSError, ValueError, TypeError) as error:
            self.chart_events = ()
            messagebox.showwarning("События не загружены", str(error), parent=self)
        self._clear_mapping()
        self._invalidate_results()
        self.file_label.configure(text=str(self.selected_file))
        self._update_input_controls()

    def review_chart_events(self):
        if self.selected_file is None or self.calculation_running or self.export_running:
            return
        dialog = ChartEventsDialog(self, self.chart_events, self.selected_file.name)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.chart_events = dialog.result
        try:
            save_chart_events(self.selected_file, self.chart_events)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showwarning(
                "Профиль событий не сохранён",
                f"События применены для текущего запуска, но не сохранены: {error}",
                parent=self,
            )
        self._invalidate_results()
        self._update_input_controls()

    def _clear_mapping(self):
        self.sensor_mappings = None
        self.mapping_sheet = None

    def choose_raw_file(self):
        if self.calculation_mode.get() != "import" or self.selected_file is None:
            return
        file_name = filedialog.askopenfilename(
            title="Выберите исходную выгрузку датчиков",
            initialdir=str(
                DATA_DIR / "initial_data"
                if (DATA_DIR / "initial_data").exists() else DATA_DIR
            ),
            filetypes=[
                ("Excel-файлы", "*.xlsx *.xlsm *.xls *.xlsb"),
                ("Все файлы", "*.*"),
            ],
        )
        if not file_name:
            return
        try:
            sheets = list_source_sheets(file_name)
        except Exception as error:
            messagebox.showerror("Не удалось открыть выгрузку", str(error), parent=self)
            return
        self.selected_raw_file = Path(file_name)
        if not self.station_manually_selected and not self.station_var.get():
            station = self.station_repository.detect_station(self.selected_raw_file)
            if station is not None:
                self._apply_station(station, automatic=True)
        self._clear_mapping()
        self.raw_sheet_combo.configure(values=sheets, state="readonly")
        name = self.selected_file.stem.lower() if self.selected_file else ""
        expected = "gt10" if "10" in name else "gt11" if "11" in name else ""
        default = next(
            (sheet for sheet in sheets if expected in sheet.lower()),
            sheets[0] if sheets else "",
        )
        self.selected_raw_sheet.set(default)
        self._invalidate_results()
        self._update_input_controls()

    def review_mapping(self) -> bool:
        if not self.selected_file or not self.selected_raw_file:
            return False
        station = self.stations_by_name.get(self.station_var.get())
        if station is None:
            messagebox.showerror("Не выбрана ТЭЦ", "Выберите ТЭЦ из списка.", parent=self)
            return False
        sheet = self.selected_raw_sheet.get().strip()
        if not sheet:
            messagebox.showerror("Не выбран лист", "Выберите лист выгрузки.", parent=self)
            return False
        try:
            headers, verified_duplicates = source_mapping_info(
                self.selected_raw_file, sheet, station_id=station.id,
                repository=self.station_repository,
            )
            suggestions = (
                load_saved_mappings(self.selected_file, headers, station_id=station.id,
                                    repository=self.station_repository)
                or suggest_mappings(
                    headers, self.selected_file, verified_duplicates,
                    station_id=station.id, repository=self.station_repository,
                )
            )
            targets = template_columns(self.selected_file)
        except Exception as error:
            messagebox.showerror("Ошибка сопоставления", str(error), parent=self)
            return False
        dialog = MappingDialog(
            self, suggestions, targets, headers, verified_duplicates, station.id
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return False
        self.sensor_mappings = dialog.result
        self.mapping_sheet = sheet
        self._invalidate_results()
        try:
            save_mappings(self.selected_file, headers, dialog.result, station_id=station.id,
                          repository=self.station_repository)
        except (OSError, ValueError) as error:
            messagebox.showwarning(
                "Профиль не сохранён",
                f"Соответствия применены, но не удалось сохранить профиль: {error}",
                parent=self,
            )
        return True

    def start_calculation(self):
        if self.selected_file is None or self.calculation_running or self.export_running:
            return
        station = self.stations_by_name.get(self.station_var.get())
        if station is None:
            messagebox.showerror("Не выбрана ТЭЦ", "Выберите ТЭЦ перед запуском расчёта.", parent=self)
            return
        importing = self.calculation_mode.get() == "import"
        raw_file_path = self.selected_raw_file if importing else None
        if importing:
            if raw_file_path is None or not self.selected_raw_sheet.get():
                messagebox.showerror(
                    "Выберите выгрузку", "Укажите файл датчиков и лист нужной ГТ.", parent=self
                )
                return
            if self.sensor_mappings is None or self.mapping_sheet != self.selected_raw_sheet.get():
                if not self.review_mapping():
                    return

        try:
            gas_tariff = self._parse_tariff(
                self.gas_tariff_var.get(), "тарифа газа"
            )
            electricity_tariff = self._parse_tariff(
                self.electricity_tariff_var.get(), "тарифа электроэнергии"
            )
            electricity_cost = self._parse_tariff(
                self.electricity_cost_var.get(), "себестоимости электроэнергии"
            )
        except ValueError as error:
            messagebox.showerror("Ошибка тарифа", str(error), parent=self)
            return

        self._clear_log()
        self._invalidate_results()
        self.calculation_running = True
        self.has_calculation_run = True
        self._update_input_controls()
        self.progress.start(10)

        worker = threading.Thread(
            target=self._calculation_worker,
            args=(
                self.selected_file,
                raw_file_path,
                self.selected_raw_sheet.get() if importing else "",
                self.sensor_mappings if importing else None,
                gas_tariff,
                electricity_tariff,
                electricity_cost,
                self.chart_events,
                station.id,
            ),
            daemon=True,
        )
        worker.start()

    @staticmethod
    def _parse_tariff(value, title):
        text = str(value).strip().replace(",", ".")
        if not text:
            raise ValueError(f"Введите значение для {title}.")
        try:
            tariff = float(text)
        except ValueError as error:
            raise ValueError(
                f"{title.capitalize()} должен быть числом."
            ) from error
        if not np.isfinite(tariff) or tariff < 0:
            raise ValueError(f"{title.capitalize()} не может быть отрицательным.")
        return tariff

    def _calculation_worker(
        self,
        file_path: Path,
        raw_file_path: Path | None,
        raw_sheet: str,
        mappings: list[SensorMapping] | None,
        gas_tariff: float,
        electricity_tariff: float,
        electricity_cost: float,
        chart_events: tuple[ChartEvent, ...] = (),
        station_id: str | None = None,
    ):
        writer = QueueWriter(self.output_queue)
        calculation_started = None

        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                station = self.station_repository.get_station(station_id)
                print(f"ТЭЦ: {station.name}")
                print(f"Выбран файл: {file_path}")
                print("Лист: Данные")

                turbine = unit_number(file_path)
                correction_profile = require_profile(file_path, station.id, turbine)
                print(f"Именованные поправки: ГТ-{turbine}, метод {correction_profile.method}, "
                      f"версия {correction_profile.revision}; 63 коэффициента.")
                passport = resolve_passport(file_path, station.id, turbine)
                corrections = read_correction_sheet(file_path)
                profile = None
                if passport is not None:
                    profile = read_calculation_profile(file_path, gas_passport=passport,
                        correction_profile=correction_profile, station_id=station.id)
                    print(f"Паспорт газа: {station.name} ГТ-{turbine}; ρ = {passport.density_kg_per_nm3:g} кг/нм³; "
                          f"Qнр = {passport.q_lower_mj_per_nm3:g} МДж/нм³; C/H = {passport.carbon_hydrogen_ratio:g}.")
                    print(f"Qнр для массовой поправки: {passport.q_lower_mj_per_kg:g} МДж/кг.")
                    if passport.composition_warning:
                        print("WARNING: " + passport.composition_warning)
                elif raw_file_path is not None:
                    raise ValueError("Нет паспорта газа для выбранной ТЭЦ и ГТ. Заполните его кнопкой «Паспорт газа».")
                else:
                    print("Паспорт газа отсутствует: готовые газозависимые колонки книги сохранены. Для их обновления заполните «Паспорт газа».")
                if corrections is None:
                    print("В экспорте будет создан именованный лист «Поправки» из используемого JSON-профиля.")

                periods_mod.PERIOD_OVERRIDES = []
                assembled = None
                if raw_file_path is not None:
                    print(f"Исходная выгрузка: {raw_file_path.name}, лист: {raw_sheet}")
                    assembled = assemble_sensor_data(
                        file_path, raw_file_path, raw_sheet, mappings or [],
                        station_id=station.id, repository=self.station_repository,
                    )
                    print(
                        f"Получасовых строк: {assembled.imported_rows}; "
                        f"совпадений по дате: {assembled.overlap_rows}."
                    )
                    if assembled.invalid_sensor_values:
                        print(
                            "Нечисловые показания сохранены без подмены: "
                            + ", ".join(
                                f"{key} — {count}"
                                for key, count in assembled.invalid_sensor_values.items()
                            )
                        )
                    if assembled.verified_duplicate_columns:
                        print(
                            "Производные колонки выгрузки совпали с исходными "
                            "каналами и не дублируются: "
                            + ", ".join(assembled.verified_duplicate_columns)
                        )
                    calculate_data_columns(assembled, profile)
                    missing = {
                        column: int(pd.to_numeric(
                            assembled.values[column], errors="coerce"
                        ).isna().sum())
                        for column in ("R", "AB", "AQ", "AV", "AX")
                    }
                    print(
                        "Строки без расчётного значения "
                        "(в том числе остановы и X): "
                        + ", ".join(f"{column} — {count}" for column, count in missing.items())
                    )
                    source = load_source_data(assembled.as_headered_frame())
                    data_for_export = assembled
                else:
                    data_for_export = read_data_sheet(file_path)
                    if passport is not None:
                        data_for_export.apply_correction_profile(profile)
                        print("Коэффициентные и газозависимые колонки обновлены по выбранным именованным профилям.")
                    source = load_source_data(data_for_export.as_headered_frame())
                if passport is not None:
                    # AK хранит массовое Qнр для полинома поправки (МДж/кг),
                    # а расчёт КПД ГТУ принимает объёмное Qнр (МДж/нм³).
                    source["q_lower"] = passport.q_lower_mj_per_nm3
                rh_data = prepare_rh_data(source)
                vna_data = prepare_vna_data(source)

                print()
                print("=" * 78)
                print("ПРЕДПРОСМОТР АВТОМАТИЧЕСКОЙ РАЗБИВКИ ПЕРИОДОВ")
                print("=" * 78)
                # В предпросмотре нужны только даты и график. Полный RH
                # печатает таблицы границ, которые после ручной правки
                # остаются в логе рядом с окончательными и путают их.
                preview_df, preview_periods = periods_mod.build_periods(rh_data)
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
                calculation_started = time.perf_counter()

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

                nominal_hours = calculate_nominal_hours(rh_df)
                economics_result = calculate_economics(
                    rh_df,
                    rh_periods,
                    gas_price_rub_per_m3=gas_tariff,
                    electricity_price_rub_per_mwh=electricity_tariff,
                    electricity_cost_rub_per_mwh=electricity_cost,
                    power_threshold=nominal_hours["power_threshold"],
                    nominal_hours=nominal_hours,
                    vna_data=vna_df,
                    delta_table=output_tables.get("delta"),
                )
                print_economics(economics_result)

                if assembled is not None:
                    apply_economic_columns(assembled, economics_result)
                sections = collect_result_tables(
                    rh_periods, output_tables, vna_results, economics_result["table"]
                )
                report_data = build_report_data(
                    source_data=source,
                    rh_data=rh_df,
                    periods_df=rh_periods,
                    boundary_table=output_tables.get("boundary"),
                    delta_table=output_tables.get("delta"),
                    vna_results=vna_results,
                    economics_result=economics_result,
                    nominal_hours=nominal_hours,
                    gas_tariff=gas_tariff,
                    electricity_tariff=electricity_tariff,
                    electricity_cost=electricity_cost,
                    source_file=file_path,
                )
                suffix = "_обновлённые_данные_результаты" if raw_file_path is not None else "_результаты"
                snapshot = CalculationSnapshot(
                    data=data_for_export, sections=sections,
                    pressure_chart=PressureChartData(
                        rh_data, rh_periods, output_tables.get("boundary"), chart_events,
                        degradation_values=vna_df,
                        degradation_deltas=output_tables.get("delta"),
                        vna_top10=vna_results,
                        rh_values=rh_df,
                        rh_results=rh_results,
                    ),
                    report_data=report_data,
                    input_files=tuple(path.resolve() for path in (file_path, raw_file_path) if path is not None),
                    filename_stem=f"{file_path.stem}{suffix}",
                    correction_sheet=corrections, gas_passport=passport,
                    correction_profile=correction_profile,
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
                    "economics_table": economics_result["table"],
                    "rh_figure": windows_figure,
                    "snapshot": snapshot,
                }))
                if calculation_started is not None:
                    print(
                        "Время вычислительной части после выбора периодов: "
                        f"{time.perf_counter() - calculation_started:.2f} с"
                    )
                print()
                print("=" * 78)
                print("ВСЁ ГОТОВО: расчёт завершён.")
                print("Проверьте результаты во вкладках. Затем сформируйте Excel и Word кнопками.")

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
                    self.calculation_running = False
                    self._update_input_controls()
                elif kind == "export_finished":
                    self._show_export_result(value)
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
        dialog.geometry(
            f"720x470+{max(0, self.winfo_rootx() + 20)}"
            f"+{max(0, self.winfo_rooty() + 80)}"
        )
        dialog.minsize(620, 380)
        dialog.configure(bg=self.colors["window"])
        dialog.transient(self)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=(
                "Проверьте автоматическую разбивку. Оставьте даты без изменений "
                "или отредактируйте их вручную. График в основном окне "
                "остаётся доступным; это окно можно передвинуть."
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
        dialog.lift(self)
        text_box.focus_force()

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
        show_empty_states(self)

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
    def _format_cell(value, decimals=3):
        if value is None or pd.isna(value):
            return "—"
        if isinstance(value, pd.Timestamp):
            return value.strftime("%d-%m-%Y %H:%M")
        if isinstance(value, float):
            return f"{value:.{decimals}f}"
        return str(value)

    def _show_table(self, key, table):
        frame = self._clear_tab(key)
        if table is None or table.empty:
            ttk.Label(frame, text="Нет данных для отображения").pack(
                anchor="center", expand=True
            )
            return

        table = delta_table_for_display(table) if key == "delta" else table.copy()
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
            width = max(110, len(column) * 9)
            if key == "economics" and column == "Период":
                width = 690
            tree.column(column, width=width, minwidth=80)

        for row in table.itertuples(index=False, name=None):
            tree.insert("", "end", values=[
                self._format_cell(value, 2 if key == "delta" and column in ("ΔNприв, %", "Δbприв, %") else 3)
                for column, value in zip(columns, row)
            ])

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
            period_number = table.attrs.get("period_number", index)
            table = table.drop(columns=["share_percent"], errors="ignore").copy()
            table.insert(3, "│₁", "│")
            table.insert(table.columns.get_loc("eta_1") + 1, "║", "║")
            table.insert(table.columns.get_loc("eta_2") + 1, "│₂", "│")
            ttk.Label(
                content,
                text=f"ПЕРИОД {period_number}: TOP-10 ИНТЕРВАЛОВ VNA",
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
        self.last_result = results["snapshot"]
        self._update_input_controls()
        self._show_figure("pressure", results.get("pressure_figure"))
        self._show_figure("vna", results.get("vna_figure"))
        self._show_table("boundary", results.get("boundary_table"))
        self._show_top10_tables(results.get("vna_results", []))
        self._show_table("delta", results.get("delta_table"))
        self._show_table("economics", results.get("economics_table"))
        self._show_figure("rh", results.get("rh_figure"))

    def generate_excel_report(self):
        self._start_export("Excel")

    def generate_word_report(self):
        self._start_export("Word")

    def _start_export(self, kind):
        if self.calculation_running or self.export_running:
            return
        snapshot = self.last_result
        if snapshot is None:
            messagebox.showinfo(
                "Сначала выполните расчёт",
                "Документы формируются после успешного расчёта выбранных данных.", parent=self,
            )
            return
        suffix = ".xlsx" if kind == "Excel" else ".docx"
        initialdir = DEFAULT_REPORT_DIR
        try:
            initialdir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Не удалось открыть папку результатов", str(error), parent=self)
            return
        output_name = filedialog.asksaveasfilename(
            title=f"Куда сохранить {kind}", initialdir=str(initialdir),
            initialfile=f"{snapshot.filename_stem}{suffix}",
            defaultextension=suffix,
            filetypes=[("Книга Excel", "*.xlsx")] if kind == "Excel" else [("Документ Word", "*.docx")],
        )
        if not output_name:
            return
        path = Path(output_name)
        try:
            snapshot.validate_destination(path, suffix)
        except ValueError as error:
            messagebox.showerror("Выберите другой файл", str(error), parent=self)
            return
        self.export_running = True
        self._update_input_controls()
        self.progress.start(10)
        self._append_log(f"\nФормирование {kind}: {path}\n")
        threading.Thread(
            target=self._export_worker, args=(snapshot, path, kind), daemon=True,
        ).start()

    def _export_worker(self, snapshot, path, kind):
        result = {"kind": kind, "path": path, "error": None}
        try:
            if kind == "Excel":
                save_result_workbook(
                    snapshot.data, snapshot.sections, path,
                    pressure_chart=snapshot.pressure_chart,
                    correction_sheet=snapshot.correction_sheet,
                    gas_passport=snapshot.gas_passport,
                    correction_profile=snapshot.correction_profile,
                )
            else:
                generate_report(snapshot.report_data, template_path=DEFAULT_TEMPLATE, output_path=path)
        except Exception as error:
            result["error"] = str(error)
            result["traceback"] = traceback.format_exc()
        self.output_queue.put(("export_finished", result))

    def _show_export_result(self, result):
        self.export_running = False
        self.progress.stop()
        self._update_input_controls()
        kind = result["kind"]
        if result["error"] is not None:
            self._append_log(f"\nОшибка формирования {kind}:\n{result['traceback']}\n")
            messagebox.showerror(f"Ошибка формирования {kind}", result["error"], parent=self)
            return
        path = result["path"].resolve()
        self._append_log(f"{kind} сохранён: {path}\n")
        messagebox.showinfo(
            f"{kind} сформирован", f"Файл сохранён:\n{path}", parent=self,
        )


def main():
    app = CalculationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
