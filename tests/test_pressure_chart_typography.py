"""Проверка шрифтов и подстрочных индексов в сохранённом XML Excel."""
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr"))
from chart_events import ChartEvent
from pressure_chart import PressureChartData, write_pressure_sheet

NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


class PressureChartTypographyTest(unittest.TestCase):
    def build(self):
        dates = pd.date_range("2025-11-08", periods=3, freq="30min")
        values = pd.DataFrame({"date": dates, "period": 1, "hours": [0., .5, 1.],
            "vlo": [194.1, 195., 196.], "fgo_fto": [275., 276., 277.],
            "power_n": [75.3, 75.1, 75.], "power": [90., 89.9, 89.8],
            "fuel_specific": [280., 281., 282.], "eta_gtu": [30., 29.9, 29.8],
            "vna": [86.2, 86.3, 86.4]})
        periods = pd.DataFrame([{"period": 1, "date_start": dates[0], "date_end": dates[-1]}])
        boundaries = pd.DataFrame([{"Период": f"1 {tag}", "дата": date,
            "ВЛО": 194.1, "ФГО+ФТО": 275., "ВНА": 86.2, "N": 75.3}
            for tag, date in (("нач", dates[0]), ("кон", dates[-1]))])
        book = Workbook(write_only=True)
        headers = ["Дата", "ВЛО, Па", "ФГО+ФТО, Па", "N, МВт"]
        book.create_sheet("Данные").append(headers)
        write_pressure_sheet(book, headers, 0, len(values) + 1,
            PressureChartData(values, periods, boundaries,
                (ChartEvent(dates[1], "Замена фильтра"),), degradation_values=values))
        buffer = io.BytesIO()
        book.save(buffer)
        buffer.seek(0)
        return buffer

    def test_axes_and_parameter_labels_are_14pt_with_small_subscripts(self):
        with ZipFile(self.build()) as archive:
            charts = [ET.fromstring(archive.read(f"xl/charts/chart{index}.xml"))
                      for index in (1, 2)]
        for chart in charts:
            axes = chart.findall(".//c:valAx", NS)
            visible = [axis for axis in axes if axis.find("c:delete", NS).get("val") == "0"]
            self.assertEqual(len(visible), 3)
            for axis in visible:
                self.assertEqual(axis.find("c:txPr/a:p/a:pPr/a:defRPr", NS).get("sz"), "1400")
                for run in axis.findall("c:title/c:tx/c:rich/a:p/a:r", NS):
                    size = "1050" if run.find("a:rPr", NS).get("baseline") == "-25000" else "1400"
                    self.assertEqual(run.find("a:rPr", NS).get("sz"), size)
            self.assertEqual(chart.find(".//c:legend/c:txPr/a:p/a:pPr/a:defRPr", NS).get("sz"), "1400")
        labels = charts[0].findall(".//c:dLbl/c:tx/c:rich", NS)
        boundary = next(label for label in labels if "αВНА" in "".join(label.itertext()))
        subscripts = [run.find("a:t", NS).text for run in boundary.findall("a:p/a:r", NS)
                      if run.find("a:rPr", NS).get("baseline") == "-25000"]
        self.assertEqual(subscripts, ["ВЛО", "ФГО+ФТО", "ВНА", "ГТУ"])
        self.assertIn("194,1 Па", "".join(boundary.itertext()))
        self.assertIn("275,0 Па", "".join(boundary.itertext()))
        self.assertTrue(any(label.find("a:bodyPr", NS).get("rot") == "-5400000" for label in labels))


if __name__ == "__main__":
    unittest.main()
