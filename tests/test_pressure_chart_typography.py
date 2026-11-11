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
    def build(self, include_fso=False):
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
        if include_fso:
            values['fso']=[10.,20.,30.]
            boundaries['ФСО']=[10.,30.]
            headers.append('ФСО, Па')
        book.create_sheet("Данные").append(headers)
        write_pressure_sheet(book, headers, 0, len(values) + 1,
            PressureChartData(values, periods, boundaries,
                (ChartEvent(dates[1], "Замена фильтра"),), degradation_values=values))
        buffer = io.BytesIO()
        book.save(buffer)
        buffer.seek(0)
        return buffer

    def test_fso_is_independent_of_combined_filter_with_its_own_excel_values_and_labels(self):
        with ZipFile(self.build(include_fso=True)) as archive:
            chart=ET.fromstring(archive.read('xl/charts/chart1.xml'))
            series=chart.findall('.//c:scatterChart/c:ser',NS)
            fso=next(item for item in series if item.find('c:tx/c:v',NS).text=='Перепад давления на ФСО')
            self.assertEqual(fso.find('c:marker/c:spPr/a:solidFill/a:srgbClr',NS).get('val'),'17BECF')
            self.assertEqual([float(item.text) for item in fso.findall('c:yVal/c:numRef/c:numCache/c:pt/c:v',NS)],
                             [10.,20.,30.])
            formula=fso.find('c:yVal/c:numRef/c:f',NS).text
            self.assertIn('$AZ$',formula)
            labels=[''.join(item.itertext()) for item in chart.findall('.//c:dLbl/c:tx/c:rich',NS)]
            self.assertTrue(any('ΔPФСО = 10,0 Па' in text for text in labels))
            self.assertTrue(any('ΔPФСО = 30,0 Па' in text for text in labels))
            combined=next(item for item in series if item.find('c:tx/c:v',NS).text=='Перепад давления на ФГО+ФТО')
            self.assertEqual([float(item.text) for item in combined.findall('c:yVal/c:numRef/c:numCache/c:pt/c:v',NS)],
                             [275.,276.,277.])

    def test_gui_fso_does_not_change_existing_curve_colors_or_input_values(self):
        from RH_raschet import plot_pressure_drops
        import matplotlib.pyplot as plt
        values=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=2,freq='30min'),
                             'fgo':[10.,11.],'fto':[20.,21.]})
        periods=pd.DataFrame(columns=['period','date_start','date_end'])
        previous=plot_pressure_drops(values,periods,show=False)
        values['fso']=[30.,31.];before=values.copy(deep=True)
        updated=plot_pressure_drops(values,periods,show=False)
        old={line.get_label():line.get_color() for line in previous.axes[0].lines}
        new={line.get_label():line.get_color() for line in updated.axes[0].lines}
        for title,color in old.items():self.assertEqual(new[title],color)
        self.assertEqual(new['Перепад ФСО, Па'],'#17BECF')
        pd.testing.assert_frame_equal(values,before)
        plt.close(previous);plt.close(updated)

    def test_axes_are_16pt_and_parameter_labels_10pt_with_small_subscripts(self):
        with ZipFile(self.build()) as archive:
            charts = [ET.fromstring(archive.read(f"xl/charts/chart{index}.xml"))
                      for index in (1, 2)]
        for chart in charts:
            axes = chart.findall(".//c:valAx", NS)
            visible = [axis for axis in axes if axis.find("c:delete", NS).get("val") == "0"]
            self.assertEqual(len(visible), 3)
            for axis in visible:
                self.assertEqual(axis.find("c:txPr/a:p/a:pPr/a:defRPr", NS).get("sz"), "1600")
                for run in axis.findall("c:title/c:tx/c:rich/a:p/a:r", NS):
                    size = "1200" if run.find("a:rPr", NS).get("baseline") == "-25000" else "1600"
                    self.assertEqual(run.find("a:rPr", NS).get("sz"), size)
            self.assertEqual(chart.find(".//c:legend/c:txPr/a:p/a:pPr/a:defRPr", NS).get("sz"), "1600")
        labels = charts[0].findall(".//c:dLbl/c:tx/c:rich", NS)
        boundary = next(label for label in labels if "αВНА" in "".join(label.itertext()))
        subscripts = [run.find("a:t", NS).text for run in boundary.findall("a:p/a:r", NS)
                      if run.find("a:rPr", NS).get("baseline") == "-25000"]
        self.assertEqual(subscripts, ["ВЛО", "ФГО+ФТО", "ВНА", "ГТУ"])
        for run in boundary.findall("a:p/a:r", NS):
            style = run.find("a:rPr", NS)
            self.assertEqual(style.get("sz"), "750" if style.get("baseline") == "-25000" else "1000")
        self.assertIn("194,1 Па", "".join(boundary.itertext()))
        self.assertIn("275,0 Па", "".join(boundary.itertext()))
        self.assertTrue(any(label.find("a:bodyPr", NS).get("rot") == "-5400000" for label in labels))


if __name__ == "__main__":
    unittest.main()
