"""Адаптер существующего сценария к Qt/HTML. Расчётные функции не копируются."""
from __future__ import annotations

import base64
import inspect
import io
import json
from pathlib import Path
import queue
import types

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox
from matplotlib.backends.backend_agg import FigureCanvasAgg

import app as workflow
import chart_events_ui as events_ui
from chart_events import format_chart_events
from station_profiles import sensor_target_columns, unit_number
from ui_theme import RESULT_TABS
from gas_passport_ui import passport_fields, passport_from_fields


# Это те же code objects, что и у проверенного сценария. Меняется только
# окружение UI: диалоги и переменные вместо Tkinter общаются с Qt WebChannel.
WORKFLOW_METHODS = (
    "_invalidate_results", "_update_input_controls", "_apply_station",
    "_on_station_changed", "_on_mode_changed", "_on_raw_sheet_changed",
    "clear_raw_file", "choose_file", "review_chart_events", "_clear_mapping",
    "choose_raw_file", "review_mapping", "start_calculation", "_parse_tariff",
    "_calculation_worker", "_poll_output", "_periods_text", "_format_cell", "review_gas_passport",
    "_build_vna_overview", "_show_results", "generate_excel_report",
    "generate_word_report", "_start_export", "_export_worker", "_show_export_result",
)


def reuse_function(function, replacements):
    """Сохраняет байткод и defaults; подменяет только зависимости представления."""
    context = dict(function.__globals__)
    context.update(replacements)
    result = types.FunctionType(function.__code__, context, function.__name__,
                                function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


class Value:
    def __init__(self, value="", changed=lambda: None):
        self.value, self.changed, self.traces = str(value), changed, []

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)
        for callback in self.traces:
            callback("", "", "write")
        self.changed()

    def trace_add(self, _mode, callback):
        self.traces.append(callback)


class Control:
    """Небольшая модель состояния прежнего виджета, без второго окна Tk."""
    def __init__(self, changed=lambda: None, **attributes):
        self.attributes = attributes
        self.changed = changed

    def configure(self, **attributes):
        self.attributes.update(attributes)
        self.changed()

    def __getitem__(self, name):
        return self.attributes[name]

    def pack(self, **_options):
        self.configure(visible=True)

    def pack_forget(self):
        self.configure(visible=False)

    def start(self, _interval):
        self.configure(active=True)

    def stop(self):
        self.configure(active=False)


class Selection:
    def __init__(self, controller):
        self.controller = controller
        self.key = "pressure"

    def select(self, key=None):
        if key is not None:
            self.key = key
            self.controller.changed()
        return self.key


class FileDialogs:
    def __init__(self, window):
        self.window = window

    @staticmethod
    def _filters(options):
        return ";;".join(f"{title} ({patterns})" for title, patterns in options["filetypes"])

    def askopenfilename(self, **options):
        return QFileDialog.getOpenFileName(self.window, options["title"],
                                           options.get("initialdir", ""), self._filters(options))[0]

    def asksaveasfilename(self, **options):
        dialog = QFileDialog(self.window, options["title"], options.get("initialdir", ""))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilter(self._filters(options))
        dialog.setDefaultSuffix(options.get("defaultextension", "").lstrip("."))
        dialog.selectFile(options.get("initialfile", ""))
        return dialog.selectedFiles()[0] if dialog.exec() else ""


class Messages:
    def __init__(self, window):
        self.window = window

    def showerror(self, title, text, **_options):
        QMessageBox.critical(self.window, title, text)

    def showwarning(self, title, text, **_options):
        QMessageBox.warning(self.window, title, text)

    def showinfo(self, title, text, **_options):
        QMessageBox.information(self.window, title, text)


class Dialog:
    def __init__(self, controller, payload):
        self.controller, self.payload = controller, payload
        self.result = None
        self.loop = QEventLoop(controller.window)

    def destroy(self):
        self.controller.dialog = None
        self.controller.dialog_changed.emit("null")
        self.loop.quit()


class MappingDialog(Dialog):
    def __init__(self, parent, suggestions, target_headers, source_headers,
                 verified_duplicates, station_id):
        super().__init__(parent, {"kind": "mapping", "title": "Соответствие каналов датчиков"})
        self._target_headers, self._source_headers = target_headers, source_headers
        self._verified_duplicates = verified_duplicates
        self._allowed_targets = sensor_target_columns(station_id, parent.station_repository)
        self._rows = []
        for suggestion in suggestions:
            header = target_headers.get(suggestion.target)
            text = f"{suggestion.target} — {header}" if suggestion.target and header else suggestion.target
            self._rows.append((suggestion.source, Value(text), Value(f"{suggestion.factor:.10g}")))
        self.payload.update(
            choices=[f"{column} — {header}" for column, header in target_headers.items()
                     if header and column in self._allowed_targets],
            rows=[{"source": source, "target": target.get(), "factor": factor.get()}
                  for source, target, factor in self._rows],
        )
        self._accept = types.MethodType(reuse_function(
            workflow.MappingDialog._accept, {"messagebox": parent.messages}), self)

    def accept(self, payload):
        rows = payload.get("rows", [])
        if len(rows) != len(self._rows):
            return
        for (_, target, factor), values in zip(self._rows, rows):
            target.set(values.get("target", ""))
            factor.set(values.get("factor", ""))
        self._accept()


class EventsDialog(Dialog):
    def __init__(self, parent, events, book_name):
        super().__init__(parent, {"kind": "events", "title": "События на графике",
                                  "book": book_name, "text": format_chart_events(events)})
        self.editor = types.SimpleNamespace(get=lambda *_args: self.text)
        self.text = self.payload["text"]
        self._apply = types.MethodType(reuse_function(
            events_ui.ChartEventsDialog._apply, {"messagebox": parent.messages}), self)

    def accept(self, payload):
        self.text = str(payload.get("text", ""))
        self._apply()


class GasPassportDialog(Dialog):
    def __init__(self, parent, passport, station_id, unit, station_name):
        super().__init__(parent, {"kind": "gasPassport", "title": f"Паспорт газа — {station_name} ГТ-{unit}",
                                  "fields": passport_fields(passport),
                                  "warning": passport.composition_warning if passport else ""})
        self.station_id, self.unit = station_id, unit

    def accept(self, payload):
        try:
            self.result = passport_from_fields(payload.get("values", {}), self.station_id, self.unit)
        except ValueError as error:
            self.controller.messages.showerror("Паспорт газа", str(error))
            return
        self.destroy()


class DesktopController(QObject):
    state_changed = Signal(str)
    view_changed = Signal(str)
    log_changed = Signal(str)
    dialog_changed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window, self.closed, self.ready = window, False, False
        self._dirty = False
        self.views, self.figures, self.logs = {}, {}, ""
        self.dialog, self.period_request = None, None
        self.messages, self.files = Messages(window), FileDialogs(window)
        replacements = {"filedialog": self.files, "messagebox": self.messages,
                        "MappingDialog": MappingDialog, "ChartEventsDialog": EventsDialog,
                        "GasPassportDialog": GasPassportDialog}
        for name in WORKFLOW_METHODS:
            descriptor = inspect.getattr_static(workflow.CalculationApp, name)
            static = isinstance(descriptor, staticmethod)
            function = descriptor.__func__ if static else descriptor
            copied = reuse_function(function, replacements)
            setattr(self, name, copied if static else types.MethodType(copied, self))

        # Те же исходные значения, что у CalculationApp.__init__.
        self.output_queue = queue.Queue()
        self.selected_file = self.selected_raw_file = None
        self.calculation_mode = Value("ready", self.changed)
        self.calculation_running = self.export_running = self.has_calculation_run = False
        self.chart_events = ()
        self.selected_raw_sheet = Value("", self.changed)
        self.sensor_mappings = self.mapping_sheet = None
        self.figure_views = []
        self.last_result = None
        self.station_repository = workflow.get_station_repository()
        self.stations_by_name = {station.name: station for station in self.station_repository.list_stations()}
        self.station_var = Value("", self.changed)
        self.station_manually_selected = False
        self.gas_tariff_var = Value("0", self.changed)
        self.electricity_tariff_var = Value("0", self.changed)
        self.electricity_cost_var = Value("0", self.changed)
        names = ("station_combo", "events_button", "choose_button", "raw_button", "mapping_button", "gas_passport_button",
                 "clear_raw_button", "raw_sheet_combo", "run_button", "excel_button", "report_button",
                 "raw_label", "file_label", "station_hint", "import_controls", "status_label", "progress")
        self.controls = {name: Control(self.changed) for name in names}
        for name, control in self.controls.items():
            setattr(self, name, control)
        self.raw_sheet_combo.configure(values=[])
        self.file_label.configure(text="Файл не выбран")
        self.station_hint.configure(text="Выберите ТЭЦ или загрузите файл.")
        self.mode_buttons = [Control(self.changed), Control(self.changed)]
        self.tariff_entries = [Control(self.changed) for _ in range(3)]
        self.chart_tabs = Selection(self)
        self.tab_frames = {key: key for key, _ in RESULT_TABS}
        for variable in (self.gas_tariff_var, self.electricity_tariff_var, self.electricity_cost_var):
            variable.trace_add("write", self._invalidate_results)
        self._update_input_controls()
        self.after(100, self._poll_output)

    def changed(self):
        if self.closed or self._dirty:
            return
        self._dirty = True
        QTimer.singleShot(0, self.publish_state)

    def publish_state(self):
        self._dirty = False
        if self.ready and not self.closed:
            self.state_changed.emit(json.dumps(self.state(), ensure_ascii=False))

    def state(self):
        return {
            "controls": {name: control.attributes for name, control in self.controls.items()},
            "values": {name: getattr(self, name).get() for name in (
                "calculation_mode", "selected_raw_sheet", "station_var", "gas_tariff_var",
                "electricity_tariff_var", "electricity_cost_var")},
            "stations": list(self.stations_by_name), "tab": self.chart_tabs.key,
            "file": str(self.selected_file) if self.selected_file else "",
            "filename": self.selected_file.name if self.selected_file else "",
            "station": self.station_var.get(), "unit": unit_number(self.selected_file.name) if self.selected_file else "",
            "modeDisabled": any(button.attributes.get("state") == "disabled" for button in self.mode_buttons),
            "tariffsDisabled": any(entry.attributes.get("state") == "disabled" for entry in self.tariff_entries),
            "running": self.calculation_running, "exporting": self.export_running,
            "hasResult": self.last_result is not None,
        }

    def after(self, milliseconds, callback):
        timer = QTimer(self)
        timer.setSingleShot(True)
        def invoke():
            timer.deleteLater()
            if not self.closed:
                callback()
        timer.timeout.connect(invoke)
        timer.start(milliseconds)
        return timer

    def update_idletasks(self):
        QCoreApplication.processEvents()

    def wait_window(self, dialog):
        self.dialog = dialog
        self.dialog_changed.emit(json.dumps(dialog.payload, ensure_ascii=False))
        dialog.loop.exec()

    def _append_log(self, text):
        self.logs += text
        if self.ready:
            self.log_changed.emit(json.dumps({"append": text}, ensure_ascii=False))

    def _clear_log(self):
        self.logs = ""
        if self.ready:
            self.log_changed.emit(json.dumps({"replace": ""}))

    def _clear_charts(self):
        for figure in self.figures.values():
            workflow.plt.close(figure)
        self.figures.clear()
        self.views.clear()
        if self.ready:
            self.view_changed.emit(json.dumps({"clear": True}))

    def _show_figure(self, key, figure):
        if figure is None:
            return
        if key in self.figures:
            workflow.plt.close(self.figures[key])
        self.figures[key] = figure
        canvas = FigureCanvasAgg(figure)
        data = io.BytesIO()
        canvas.print_png(data)
        self.set_view(key, {"type": "figure", "src": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")})

    def _table(self, table, key=""):
        if table is None or table.empty:
            return {"columns": [], "rows": []}
        table = workflow.delta_table_for_display(table) if key == "delta" else table.copy()
        columns = [str(column) for column in table.columns]
        return {"columns": columns, "rows": [[
            self._format_cell(value, 2 if key == "delta" and column in ("ΔNприв, %", "Δbприв, %") else 3)
            for column, value in zip(columns, row)]
            for row in table.itertuples(index=False, name=None)]}

    def _show_table(self, key, table):
        self.set_view(key, {"type": "table", **self._table(table, key)})

    def _show_top10_tables(self, results):
        tables = []
        for index, table in enumerate(results, start=1):
            period = table.attrs.get("period_number", index)
            display = table.drop(columns=["share_percent"], errors="ignore").copy()
            tables.append({"title": f"Период {period} · ТОП-10 ВНА", **self._table(display)})
        self.set_view("top10", {"type": "tables", "tables": tables})

    def set_view(self, key, payload):
        self.views[key] = payload
        if self.ready:
            self.view_changed.emit(json.dumps({"key": key, "view": payload}, ensure_ascii=False))

    def _show_period_choice(self, request):
        self.period_request = request
        self.dialog_changed.emit(json.dumps({"kind": "periods", "title": "Проверка периодов",
            "text": self._periods_text(request["periods_df"])}, ensure_ascii=False))

    def resolve_dialog(self, payload):
        if self.period_request is not None:
            request = self.period_request
            manual = payload.get("action") == "manual"
            overrides = None
            if manual:
                lines = [line.strip() for line in payload.get("text", "").splitlines() if line.strip()]
                if not lines:
                    self.messages.showerror("Периоды не заданы", "Введите хотя бы один период или выберите автоматическую разбивку.")
                    return
                try:
                    overrides = workflow.parse_periods_arg("|".join(lines))
                except ValueError as error:
                    self.messages.showerror("Ошибка формата дат", str(error))
                    return
            request["overrides"] = overrides
            self.period_request = None
            self.dialog_changed.emit("null")
            request["event"].set()
        elif self.dialog is not None:
            if payload.get("action") == "cancel":
                self.dialog.destroy()
            else:
                self.dialog.accept(payload)

    @Slot()
    def connect_ui(self):
        self.ready = True
        self.publish_state()
        for key, view in self.views.items():
            self.view_changed.emit(json.dumps({"key": key, "view": view}, ensure_ascii=False))
        self.log_changed.emit(json.dumps({"replace": self.logs}, ensure_ascii=False))

    @Slot(str, str)
    def action(self, name, data):
        # Сначала возвращаем управление WebChannel. Иначе вложенное ожидание
        # диалога держит IPC-вызов открытым, и WebEngine не исполняет ответ JS.
        self.after(0, lambda: self.dispatch(name, data))

    def dispatch(self, name, data):
        if self.closed:
            return
        payload = json.loads(data or "{}")
        if name == "dialog":
            self.resolve_dialog(payload)
            return
        if self.dialog is not None or self.period_request is not None:
            if name == "tab" and self.period_request is not None:
                self.chart_tabs.select(payload.get("key", "pressure"))
            return
        actions = {"file": self.choose_file, "raw": self.choose_raw_file,
                   "gasPassport": self.review_gas_passport,
                   "clearRaw": self.clear_raw_file, "mapping": self.review_mapping,
                   "events": self.review_chart_events, "run": self.start_calculation,
                   "excel": self.generate_excel_report, "word": self.generate_word_report}
        guards = {"file": "choose_button", "raw": "raw_button", "clearRaw": "clear_raw_button",
                  "gasPassport": "gas_passport_button",
                  "mapping": "mapping_button", "events": "events_button", "run": "run_button",
                  "excel": "excel_button", "word": "report_button"}
        if name in actions:
            if self.controls[guards[name]].attributes.get("state") != "disabled":
                actions[name]()
        elif name == "tab" and payload.get("key") in self.tab_frames:
            self.chart_tabs.select(payload["key"])
        elif name == "value" and not (self.calculation_running or self.export_running):
            key, value = payload.get("key"), payload.get("value", "")
            fields = {"station": (self.station_var, self._on_station_changed),
                      "mode": (self.calculation_mode, self._on_mode_changed),
                      "sheet": (self.selected_raw_sheet, self._on_raw_sheet_changed),
                      "gas": (self.gas_tariff_var, None), "electricity": (self.electricity_tariff_var, None),
                      "cost": (self.electricity_cost_var, None)}
            if key in fields:
                variable, callback = fields[key]
                variable.set(value)
                if callback:
                    callback()
