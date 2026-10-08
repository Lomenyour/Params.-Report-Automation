# -*- coding: utf-8 -*-
"""Графическое окно для расчётов ГТУ."""
from __future__ import annotations

import contextlib
import queue
import sys
import threading
import traceback
from pathlib import Path

import matplotlib

# Графики строятся в памяти, а затем встраиваются во вкладки Tkinter.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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


class CalculationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Параметрический расчёт ГТУ")
        self.geometry("1200x800")
        self.minsize(900, 600)

        self.output_queue: queue.Queue = queue.Queue()
        self.selected_file: Path | None = None
        self.figure_canvases = []

        self._build_widgets()
        self.after(100, self._poll_output)

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

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_frame = ttk.LabelFrame(panes, text="Лог расчёта", padding=5)
        panes.add(log_frame, weight=1)

        self.log = tk.Text(log_frame, wrap="none", state="disabled")
        log_scroll_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll_y.grid(row=0, column=1, sticky="ns")
        log_scroll_x.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        chart_frame = ttk.LabelFrame(panes, text="Графики", padding=5)
        panes.add(chart_frame, weight=2)

        self.chart_tabs = ttk.Notebook(chart_frame)
        self.chart_tabs.pack(fill="both", expand=True)

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
                print("РАСЧЁТ ВНА")
                print("=" * 78)
                vna_df, vna_periods, _, vna_figures = run_vna(
                    data=vna_data,
                    show_plots=False,
                )

                print()
                print("=" * 78)
                print("РАСЧЁТ РАСХОДНОЙ ХАРАКТЕРИСТИКИ")
                print("=" * 78)
                rh_df, rh_periods, rh_results, _ = run_rh(
                    rh_data,
                    periods_only=False,
                    show_plots=False,
                    vna_data=vna_df,
                )

                figures = [(f"ВНА — период {index}", figure)
                           for index, figure in enumerate(vna_figures, start=1)]

                pressure_figure = plot_pressure_drops(
                    rh_df,
                    rh_periods,
                    show=False,
                )
                if pressure_figure is not None:
                    figures.insert(0, ("Перепады давления", pressure_figure))

                windows_figure = plot_selected_windows(
                    rh_df,
                    rh_results,
                    show=False,
                )
                if windows_figure is not None:
                    figures.append(("Расходная характеристика", windows_figure))

                self.output_queue.put(("figures", figures))
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
                elif kind == "figures":
                    self._show_figures(value)
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
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _clear_charts(self):
        for canvas in self.figure_canvases:
            canvas.figure.clear()
            plt.close(canvas.figure)
        self.figure_canvases.clear()
        for tab in self.chart_tabs.tabs():
            self.chart_tabs.forget(tab)

    def _show_figures(self, figures):
        for title, figure in figures:
            frame = ttk.Frame(self.chart_tabs)
            canvas = FigureCanvasTkAgg(figure, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.chart_tabs.add(frame, text=title)
            self.figure_canvases.append(canvas)


def main():
    app = CalculationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
