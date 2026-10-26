"""Привязка тарифов и каналов к ТЭЦ и обязательный выбор в приложении."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from data_assembly import (SensorMapping, _read_sensor_sheet, _verified_duplicates,
                           load_saved_mappings, save_mappings, suggest_mappings)
from station_profiles import (JsonStationRepository, catalog_path,
                              get_station_repository, unit_number)


class StationProfilesTest(unittest.TestCase):
    def setUp(self):
        self.repository = get_station_repository()

    def test_detection_and_tariffs(self):
        for filename in ("СызТЭЦ ГТ-11 2кв.xlsm", "сызтэц ГТ-10.xlsx",
                         "Сызранская_ТЭЦ ГТ-11.xlsx", "Сыз-ТЭЦ ГТ-11.xlsx"):
            self.assertEqual(self.repository.detect_station(filename).id, "syz_tec")
        self.assertIsNone(self.repository.detect_station("НКТЭЦ ГТ-11.xlsx"))
        self.assertIsNone(self.repository.detect_station("данные.xlsx"))
        self.assertEqual(unit_number("Новая ТЭЦ ГТ-123.xlsx"), "123")
        tariffs = self.repository.get_tariffs("syz_tec")
        self.assertEqual((tariffs.gas_rub_per_nm3, tariffs.electricity_rub_per_mwh,
                          tariffs.electricity_cost_rub_per_mwh), (7.773, 2253.66, 1200.))

    def test_all_original_sensor_assignments_and_factors_are_preserved(self):
        expected = [
            ("ATID_C", "F", 1.), ("RHUM", "G", 1.),
            ("AFPAP1A_C", "C", 133.322368), ("APCS_c", "L", 9.80665),
            ("TR96TF2_c", "J", 9.80665), ("TR96TF3_c", "K", 9.80665),
            ("AFPCS_c", "M", 9.80665), ("CTIM_C", "P", 1.),
            ("CPD_C", "X", 1.), ("CTDA_C", "W", 1.), ("CSGV", "V", 1.),
            ("FQG_C", "AS", 1.), ("FPG2_C", "AG", 1.),
            ("TTXM_C", "AF", 1.), ("FTG_C", "AH", 1.),
        ]
        for gt, prefix, aggregate, exhaust in (("10", "G1", "1", "01"),
                                                ("11", "G2", "2", "02")):
            rows = [(f"{prefix}.{suffix}", target, factor)
                    for suffix, target, factor in expected]
            rows += [(f"{aggregate}AGUST_DWATTXJ026", "AO", 1.),
                     (f"{aggregate}AGUST_TNH_RPMXJ022", "AM", 1.),
                     (f"{exhaust}HNE90CP001XJ016", "AC", 1.)]
            mappings = suggest_mappings([code for code, _, _ in rows],
                                        f"СызТЭЦ ГТ-{gt}.xlsx", station_id="syz_tec")
            self.assertEqual([(item.source, item.target, item.factor) for item in mappings], rows)

    def test_unknown_station_has_no_implicit_syzran_mapping(self):
        headers = ["date", "time", "G2.CTIM_C"]
        self.assertEqual(suggest_mappings(headers, "НКТЭЦ ГТ-11.xlsx")[0].target, "")
        self.assertEqual(suggest_mappings(headers, "НКТЭЦ ГТ-11.xlsx",
                                         station_id="syz_tec")[0].target, "P")

    def test_repository_keys_isolate_stations_and_saved_mappings(self):
        raw = json.loads(catalog_path().read_text(encoding="utf-8"))
        raw["stations"].append({"id": "other", "name": "Другая ТЭЦ",
                                "filename_aliases": ["ДругаяТЭЦ"]})
        raw["tariffs"].append({"station_id": "other", "gas_rub_per_nm3": 1.,
                               "electricity_rub_per_mwh": 2.,
                               "electricity_cost_rub_per_mwh": 0.})
        raw["sensor_channels"].append({"station_id": "other", "unit_number": "11",
                                       "parameter_id": "vna", "code": "LOCAL.VNA", "factor": 1.})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stations.json"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            repository = JsonStationRepository(path)
            headers = ["G2.CTIM_C", "LOCAL.VNA"]
            suggestions = suggest_mappings(headers, "ДругаяТЭЦ ГТ-11.xlsx", repository=repository)
            self.assertEqual([item.target for item in suggestions], ["", "V"])
            self.assertEqual(repository.get_tariffs("other").electricity_rub_per_mwh, 2.)
            with patch("data_assembly._mapping_profile_path", return_value=Path(folder) / "saved.json"):
                first, second = [SensorMapping("G2.CTIM_C", "P")], [SensorMapping("G2.CTIM_C", "V")]
                for station_id, mappings in (("syz_tec", first), ("other", second)):
                    save_mappings("ГТ-11.xlsx", headers, mappings,
                                  station_id=station_id, repository=repository)
                for station_id, expected in (("syz_tec", first), ("other", second)):
                    self.assertEqual(load_saved_mappings("ГТ-11.xlsx", headers,
                                     station_id=station_id, repository=repository), expected)
            invalid = copy.deepcopy(raw)
            invalid["sensor_channels"][0]["station_id"] = "missing"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Неизвестная ТЭЦ"):
                JsonStationRepository(path)

    def test_duplicates_still_require_equal_sensor_values(self):
        raw = pd.DataFrame({"ВЗТ": [9.80665, 19.6133], "G2.AFPCS_c": [1., 2.]})
        self.assertEqual(_verified_duplicates(raw, "syz_tec"), {"ВЗТ"})
        raw.loc[1, "ВЗТ"] = 500.
        self.assertEqual(_verified_duplicates(raw, "syz_tec"), set())

    def test_legacy_saved_mapping_is_reused_only_for_recognized_station(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "saved.json"
            path.write_text(json.dumps({"сызтэц|11|G2.CTIM_C": [
                {"source": "G2.CTIM_C", "target": "P", "factor": 2.}
            ]}), encoding="utf-8")
            with patch("data_assembly._mapping_profile_path", return_value=path):
                self.assertEqual(load_saved_mappings("СызТЭЦ ГТ-11.xlsx", ["G2.CTIM_C"]),
                                 [SensorMapping("G2.CTIM_C", "P", 2.)])
                self.assertIsNone(load_saved_mappings("другая ГТ-11.xlsx", ["G2.CTIM_C"],
                                                      station_id="syz_tec"))

    def test_import_still_selects_only_half_hour_records_and_rejects_duplicates(self):
        def read(times):
            book = Workbook()
            sheet = book.active
            sheet.title = "GT11"
            sheet.append(["date", "time", "G2.CTIM_C"])
            for index, time in enumerate(times):
                sheet.append([pd.Timestamp("2026-01-01").to_pydatetime(), time, float(index)])
            buffer = io.BytesIO()
            book.save(buffer)
            buffer.seek(0)
            reader = pd.ExcelFile(buffer, engine="calamine")
            with patch("data_assembly.pd.ExcelFile", return_value=reader):
                return _read_sensor_sheet("sensors.xlsx", "GT11")

        result = read(["00:00:00", "00:10:00", "00:20:00", "00:30:00", "00:40:00"])
        self.assertEqual(result["G2.CTIM_C"].tolist(), [0., 3.])
        with self.assertRaisesRegex(ValueError, "повторяются даты"):
            read(["00:00:00", "00:00:00"])

    def test_frozen_catalog_can_be_loaded_from_bundle_or_next_to_exe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("station_profiles.sys.frozen", True, create=True), \
                 patch("station_profiles.sys.executable", str(root / "app.exe")), \
                 patch("station_profiles.sys._MEIPASS", str(root / "_internal"), create=True):
                self.assertEqual(catalog_path(), root / "_internal" / "config" / "stations.json")
                (root / "config").mkdir()
                (root / "config" / "stations.json").write_text("{}", encoding="utf-8")
                self.assertEqual(catalog_path(), root / "config" / "stations.json")


class StationGuiTest(unittest.TestCase):
    def setUp(self):
        from app import CalculationApp
        self.app = CalculationApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_no_station_blocks_button_and_direct_start(self):
        self.app.selected_file = Path("неизвестная книга.xlsx")
        self.app._update_input_controls()
        self.assertEqual(str(self.app.run_button["state"]), "disabled")
        with patch("app.messagebox.showerror") as error, patch("app.threading.Thread") as worker:
            self.app.start_calculation()
        error.assert_called_once()
        worker.assert_not_called()

    def test_file_detection_tariff_editing_manual_selection_and_mapping_reset(self):
        with patch("app.filedialog.askopenfilename", return_value="СызТЭЦ ГТ-11.xlsx"), \
             patch("app.load_chart_events", return_value=()):
            self.app.choose_file()
        self.assertEqual(self.app.station_var.get(), "СызТЭЦ")
        self.assertEqual([self.app.gas_tariff_var.get(), self.app.electricity_tariff_var.get(),
                          self.app.electricity_cost_var.get()], ["7,773", "2253,66", "1200"])
        self.assertEqual(str(self.app.run_button["state"]), "normal")
        self.app.gas_tariff_var.set("9,123")
        self.app.calculation_mode.set("import")
        self.app._on_mode_changed()
        with patch("app.filedialog.askopenfilename", return_value="датчики.xlsx"), \
             patch("app.list_source_sheets", return_value=["GT11"]):
            self.app.choose_raw_file()
        self.assertEqual(self.app.gas_tariff_var.get(), "9,123")
        self.app.sensor_mappings = [SensorMapping("G2.CSGV", "V")]
        self.app.last_result = object()
        self.app._on_station_changed()
        self.assertTrue(self.app.station_manually_selected)
        self.assertIsNone(self.app.sensor_mappings)
        self.assertIsNone(self.app.last_result)
        self.assertEqual(self.app.gas_tariff_var.get(), "7,773")

    def test_unknown_file_clears_auto_selection_and_manual_override_works(self):
        for filename in ("СызТЭЦ ГТ-11.xlsx", "НКТЭЦ ГТ-11.xlsx"):
            with patch("app.filedialog.askopenfilename", return_value=filename), \
                 patch("app.load_chart_events", return_value=()):
                self.app.choose_file()
        self.assertEqual(self.app.station_var.get(), "")
        self.assertEqual(str(self.app.run_button["state"]), "disabled")
        self.app.station_var.set("СызТЭЦ")
        self.app._on_station_changed()
        self.assertEqual(str(self.app.run_button["state"]), "normal")

    def test_start_passes_selected_station_and_manual_tariffs_to_worker(self):
        self.app.selected_file = Path("СызТЭЦ ГТ-11.xlsx")
        self.app._apply_station(get_station_repository().get_station("syz_tec"), automatic=True)
        self.app.gas_tariff_var.set("9,5")
        self.app.electricity_tariff_var.set("2400.25")
        self.app.electricity_cost_var.set("1100")
        with patch("app.threading.Thread") as worker:
            self.app.start_calculation()
        args = worker.call_args.kwargs["args"]
        self.assertEqual(args[4:7], (9.5, 2400.25, 1100.))
        self.assertEqual(args[-1], "syz_tec")


if __name__ == "__main__":
    unittest.main()
