"""Построчный расчёт, совмещение по датам и сохранение непрофильных данных."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from data_assembly import (AssembledData, SensorMapping, _profile_cells,
                           assemble_sensor_data, calculate_data_columns)


class DataRowIntegrityTest(unittest.TestCase):
    def profile(self):
        result = dict.fromkeys(_profile_cells(), 0.0)
        result.update({"N669": 1.0, "AF788": 1.0, "AD888": 1.0,
                       "P712": 1.0, "T507": 1.0, "AE969": 1.0,
                       "U1107": 1.0, "T1019": 1.0, "AX851": 1.0,
                       "M605": .05, "O605": 100.0,
                       "gas_c_h": 3.0, "qnr_denominator": 1.0})
        return result

    def calculate(self, values):
        data = AssembledData(values.copy(deep=True), {}, 0, 0, {}, [])
        return calculate_data_columns(data, self.profile()).values

    def test_each_row_matches_calculation_in_isolation_and_after_permutation(self):
        raw = pd.DataFrame({
            "C": [100100., 99000., 101200.], "F": [10., 17., 3.],
            "G": [50., 40., 60.], "L": [200., 300., 100.],
            "M": [220., 320., 120.], "P": [12., 19., 5.],
            "X": [1.31, 1.42, 1.25], "W": [365., 388., 350.],
            "AC": [0.8, 1.1, 0.7], "AH": [20., 30., 10.],
            "AM": [5100., 5150., 5200.], "AO": [85., 90., 80.],
            "AS": [4., 5., 3.], "BD": [111., 222., 333.],
        }, index=pd.to_datetime(["2026-02-03", "2026-01-05", "2026-04-01"]))
        original = raw.copy(deep=True)
        batch = self.calculate(raw)
        computed = [column for column in batch if column not in raw and
                    column not in {"AP", "AR", "AU", "AW"}]
        for index in raw.index:
            single = self.calculate(raw.loc[[index]])
            np.testing.assert_allclose(batch.loc[index, computed].to_numpy(dtype=float),
                                       single.loc[index, computed].to_numpy(dtype=float),
                                       equal_nan=True, rtol=1e-12)
        shuffled = self.calculate(raw.iloc[[2, 0, 1]])
        pd.testing.assert_frame_equal(batch[computed], shuffled[computed].reindex(batch.index))
        pd.testing.assert_frame_equal(batch[raw.columns], original)
        pd.testing.assert_frame_equal(raw, original)

    def test_merge_keeps_unlabelled_columns_and_undated_rows(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "Данные"
        header = [None] * 56
        header[1], header[15], header[27] = "Дата", "Тнк, °С", "ηoi_Cprop"
        sheet.append(header)
        first, second = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")
        for date, temperature, marker in ((second, 20., 222.), (first, 10., 111.)):
            row = [None] * 56
            row[1], row[15], row[27], row[55] = date.to_pydatetime(), temperature, 85., marker
            row[28], row[29] = (0.7, 123.) if date == second else (None, 0.8)
            sheet.append(row)
        tail = [None] * 56
        tail[55] = "unlabelled summary retained"
        sheet.append(tail)
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        sensors = pd.DataFrame({"G2.CTIM_C": [12.]}, index=pd.DatetimeIndex([first]))
        reader = pd.ExcelFile(output, engine="calamine")
        with patch("data_assembly.pd.ExcelFile", return_value=reader), \
             patch("data_assembly._read_sensor_sheet", return_value=sensors):
            assembled = assemble_sensor_data("test.xlsx", "sensors.xlsx", "GT", [
                SensorMapping("G2.CTIM_C", "P", 1.)
            ])
        self.assertEqual(assembled.values["BD"].tolist(), [111., 222.])
        self.assertEqual(assembled.values["P"].tolist(), [12., 20.])
        self.assertEqual(assembled.values["AC"].tolist(), [0.8, 0.7])
        self.assertEqual(assembled.values["AD"].tolist(), [0.8, 123.])
        self.assertEqual(assembled.undated_rows.iloc[0]["BD"], "unlabelled summary retained")

        # Пишем в память через общий экспортный writer, без изменений исходной книги.
        from result_export import _write_data_sheet
        exported = Workbook(write_only=True)
        _write_data_sheet(exported, assembled)
        out = io.BytesIO()
        exported.save(out)
        out.seek(0)
        reread = pd.read_excel(out, header=None, engine="calamine")
        self.assertEqual(reread.iloc[1:, 55].tolist(), [111., 222., "unlabelled summary retained"])
        self.assertEqual(reread.iloc[1:3, 15].tolist(), [12., 20.])


if __name__ == "__main__":
    unittest.main()
