"""Новая оболочка использует прежние обработчики и не меняет данные расчёта."""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
import app as workflow
from calculation_snapshot import CalculationSnapshot
from data_assembly import SensorMapping
from desktop_controller import DesktopController, EventsDialog, MappingDialog, GasPassportDialog, CorrectionDialog, WORKFLOW_METHODS


_application = None


class DesktopBridgeTest(unittest.TestCase):
    def test_correction_dialog_requires_all_fields_and_preserves_identity(self):
        from correction_profiles import FIELDS
        c=self.controller
        dialog=CorrectionDialog(c,None,"syz_tec","10","СызТЭЦ")
        c.dialog=dialog
        dialog.accept({"values":{}})
        self.assertIs(c.dialog,dialog)
        self.assertIsNone(dialog.result)
        dialog.accept({"values":{field.key:"1,234E-5" for field in FIELDS}})
        self.assertIsNone(c.dialog)
        self.assertEqual(dialog.result.unit,"10")
        self.assertEqual(len(dialog.result.values),63)
        self.assertEqual(dialog.result.values["pressure_power.p1"],1.234e-5)

    def test_gas_dialog_validates_without_closing_on_bad_input(self):
        c = self.controller
        dialog = GasPassportDialog(c, None, "syz_tec", "11", "СызТЭЦ")
        c.dialog = dialog
        dialog.accept({"values": {"density_kg_per_nm3": "-1"}})
        self.assertIs(c.dialog, dialog)
        self.assertIsNone(dialog.result)
        c.messages.showerror.assert_called_once()
        dialog.accept({"values": {"density_kg_per_nm3": "0,7", "q_lower_mj_per_nm3": "34,13",
                                    "carbon_hydrogen_ratio": "3,066677", "component:Methane": "1"}})
        self.assertIsNone(c.dialog)
        self.assertEqual(dialog.result.unit, "11")
        self.assertEqual(dialog.result.q_lower_mj_per_nm3, 34.13)

    def setUp(self):
        global _application
        _application = QApplication.instance() or QApplication([])
        self.window = QWidget()
        self.controller = DesktopController(self.window)
        self.controller.messages.showerror = Mock()
        self.controller.messages.showinfo = Mock()
        self.controller.messages.showwarning = Mock()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.closed = True
        self.controller._clear_charts()
        self.window.close()
        self.window.deleteLater()
        _application.processEvents()

    def choose_book(self, filename="СызТЭЦ ГТ-11.xlsx"):
        function_globals = self.controller.choose_file.__func__.__globals__
        with patch.object(self.controller.files, "askopenfilename", return_value=filename), \
             patch.dict(function_globals, load_chart_events=Mock(return_value=())):
            self.controller.choose_file()

    def test_every_reused_method_has_the_original_code_and_defaults(self):
        for name in WORKFLOW_METHODS:
            with self.subTest(method=name):
                descriptor = inspect.getattr_static(workflow.CalculationApp, name)
                original = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor
                actual = getattr(self.controller, name)
                actual = getattr(actual, "__func__", actual)
                self.assertIs(actual.__code__, original.__code__)
                self.assertEqual(actual.__defaults__, original.__defaults__)
                self.assertEqual(actual.__kwdefaults__, original.__kwdefaults__)

    def test_station_tariffs_and_invalidation_match_existing_gui(self):
        self.choose_book()
        c = self.controller
        self.assertEqual(c.station_var.get(), "СызТЭЦ")
        self.assertEqual([c.gas_tariff_var.get(), c.electricity_tariff_var.get(),
                          c.electricity_cost_var.get()], ["7,773", "2253,66", "1200"])
        self.assertEqual(c.run_button["state"], "normal")
        c.last_result = object()
        c.dispatch("value", json.dumps({"key": "gas", "value": "9,5"}))
        self.assertEqual(c.gas_tariff_var.get(), "9,5")
        self.assertIsNone(c.last_result)
        self.assertEqual(c.excel_button["state"], "disabled")
        self.choose_book("НКТЭЦ ГТ-11.xlsx")
        self.assertEqual(c.station_var.get(), "")
        self.assertEqual(c.run_button["state"], "disabled")

    def test_button_guard_and_running_state_reject_ui_mutations(self):
        c = self.controller
        with patch.object(workflow.threading, "Thread") as thread:
            c.dispatch("run", "{}")
        thread.assert_not_called()
        self.choose_book()
        c.calculation_running = True
        c._update_input_controls()
        before = c.gas_tariff_var.get()
        c.dispatch("value", json.dumps({"key": "gas", "value": "123"}))
        self.assertEqual(c.gas_tariff_var.get(), before)
        self.assertEqual(c.run_button["state"], "disabled")

    def test_start_passes_the_same_station_inputs_and_tariffs_to_original_worker(self):
        self.choose_book()
        c = self.controller
        c.gas_tariff_var.set("9,5")
        c.electricity_tariff_var.set("2400.25")
        c.electricity_cost_var.set("1100")
        with patch.object(workflow.threading, "Thread") as thread:
            c.start_calculation()
        args = thread.call_args.kwargs["args"]
        self.assertEqual(args[4:7], (9.5, 2400.25, 1100.))
        self.assertEqual(args[-1], "syz_tec")
        self.assertIs(thread.call_args.kwargs["target"].__func__.__code__, workflow.CalculationApp._calculation_worker.__code__)

    def test_import_mode_keeps_sheet_choice_and_manual_tariffs(self):
        self.choose_book()
        c = self.controller
        c.gas_tariff_var.set("9,123")
        c.dispatch("value", json.dumps({"key": "mode", "value": "import"}))
        with patch.object(c.files, "askopenfilename", return_value="датчики.xlsx"), \
             patch.dict(c.choose_raw_file.__func__.__globals__, list_source_sheets=Mock(return_value=["GT10", "GT11"])):
            c.choose_raw_file()
        self.assertEqual(c.selected_raw_sheet.get(), "GT11")
        self.assertEqual(c.gas_tariff_var.get(), "9,123")
        self.assertTrue(c.import_controls["visible"])
        self.assertEqual(c.mapping_button["state"], "normal")
        c.clear_raw_file()
        self.assertIsNone(c.selected_raw_file)
        self.assertEqual(c.run_button["state"], "disabled")

    def test_period_confirmation_preserves_auto_and_manual_semantics(self):
        c = self.controller
        for text in ("", "не дата"):
            request = {"event": threading.Event(), "overrides": None,
                       "periods_df": pd.DataFrame()}
            c._show_period_choice(request)
            c.resolve_dialog({"action": "manual", "text": text})
            self.assertFalse(request["event"].is_set())
        text = "01-01-2026 00:00;02-01-2026 00:00"
        c.resolve_dialog({"action": "manual", "text": text})
        self.assertTrue(request["event"].is_set())
        self.assertEqual(request["overrides"], workflow.parse_periods_arg(text))
        request = {"event": threading.Event(), "overrides": None, "periods_df": pd.DataFrame()}
        c._show_period_choice(request)
        c.resolve_dialog({"action": "auto"})
        self.assertTrue(request["event"].is_set())
        self.assertIsNone(request["overrides"])

    def test_mapping_and_events_use_original_validators(self):
        c = self.controller
        dialog = MappingDialog(c, [SensorMapping("CH", "P", 1.)],
                               {"P": "Тнк, °С"}, ["CH"], set(), "syz_tec")
        dialog.accept({"rows": [{"target": "P — Тнк, °С", "factor": "2,5"}]})
        self.assertEqual(dialog.result, [SensorMapping("CH", "P", 2.5)])
        self.assertIs(dialog._accept.__func__.__code__, workflow.MappingDialog._accept.__code__)
        events = EventsDialog(c, (), "пример.xlsx")
        events.accept({"text": "01.05.2026; Замена ВЛО"})
        self.assertEqual(len(events.result), 1)
        self.assertIs(events._apply.__func__.__code__, workflow.ChartEventsDialog._apply.__code__)

    def test_figure_render_and_table_display_do_not_modify_source_objects(self):
        c = self.controller
        figure = Figure(figsize=(4, 2), dpi=100)
        axis = figure.subplots()
        line, = axis.plot([1, 2], [3, 4])
        size = figure.get_size_inches().copy()
        c._show_figure("pressure", figure)
        self.assertTrue(c.views["pressure"]["src"].startswith("data:image/png;base64,"))
        np.testing.assert_equal(figure.get_size_inches(), size)
        np.testing.assert_equal(line.get_ydata(), [3, 4])
        table = pd.DataFrame({"Дата": [pd.Timestamp("2026-01-01")], "Значение": [1.234567]})
        before = table.copy(deep=True)
        c._show_table("boundary", table)
        self.assertEqual(c.views["boundary"]["rows"], [["01-01-2026 00:00", "1.235"]])
        pd.testing.assert_frame_equal(table, before)

    def test_export_uses_the_original_snapshot_and_worker(self):
        self.choose_book()
        c = self.controller
        snapshot = CalculationSnapshot(None, [], None, {}, (Path("input.xlsx"),), "пример")
        c.last_result = snapshot
        c._update_input_controls()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.xlsx"
            with patch.object(c.files, "asksaveasfilename", return_value=str(destination)), \
                 patch.dict(c._start_export.__func__.__globals__, DEFAULT_REPORT_DIR=Path(directory)), \
                 patch.object(workflow.threading, "Thread") as thread:
                c.generate_excel_report()
            self.assertIs(thread.call_args.kwargs["args"][0], snapshot)
            self.assertEqual(thread.call_args.kwargs["args"][1:], (destination, "Excel"))
            self.assertIs(thread.call_args.kwargs["target"].__func__.__code__, workflow.CalculationApp._export_worker.__code__)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
