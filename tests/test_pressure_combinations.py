"""Every pressure subset stays independent in GUI, Excel and boundary values."""
import contextlib
import io
import itertools
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from data_loader import PRESSURE_KEYS, available_pressure_channels
from RH_raschet import build_boundary_table, plot_pressure_drops, OPTIONAL_TITLES
from pressure_chart import PressureChartData, pressure_channels, write_pressure_sheet, PRESSURE_CHANNELS
from app import CalculationApp

NS={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}


class PressureCombinationsTest(unittest.TestCase):
    def fixture(self,keys):
        dates=pd.date_range('2026-01-01',periods=3,freq='30min')
        values=pd.DataFrame({'date':dates,'period':1,'power':90.,'power_n':90.,'vna':85.,
                             'excel_row':[2,3,4]})
        for index,key in enumerate(PRESSURE_KEYS):
            if key in keys:values[key]=[10.+index*20,15.+index*20,20.+index*20]
        periods=pd.DataFrame([{'period':1,'date_start':dates[0],'date_end':dates[-1]}])
        return values,periods

    def excel(self,values,periods,boundaries):
        keys=available_pressure_channels(values)
        book=Workbook(write_only=True)
        headers=['Дата','N, МВт']+[PRESSURE_CHANNELS[key][0] for key in keys]
        source=book.create_sheet('Данные');source.append(headers)
        for _,row in values.iterrows():
            source.append([row.date.to_pydatetime(),row.power_n]+[row[key] for key in keys])
        write_pressure_sheet(book,headers,0,len(values)+1,PressureChartData(values,periods,boundaries))
        output=io.BytesIO();book.save(output);output.seek(0)
        return output

    def test_all_32_subsets_keep_gui_and_excel_series_and_boundary_columns(self):
        for count in range(len(PRESSURE_KEYS)+1):
            for subset in itertools.combinations(PRESSURE_KEYS,count):
                with self.subTest(subset=subset):
                    values,periods=self.fixture(subset);before=values.copy(deep=True)
                    boundaries=build_boundary_table(values,periods)
                    self.assertEqual(pressure_channels(values),list(subset))
                    with contextlib.redirect_stdout(io.StringIO()):
                        figure=plot_pressure_drops(values,periods,show=False)
                    if not subset:self.assertIsNone(figure)
                    else:
                        labels=[line.get_label() for line in figure.axes[0].lines if line.get_label().startswith('Перепад ')]
                        self.assertEqual(labels,[f'Перепад {OPTIONAL_TITLES[key]}, Па' for key in subset])
                        plt.close(figure)
                    output=self.excel(values,periods,boundaries)
                    with ZipFile(output) as archive:
                        charts=[ET.fromstring(archive.read(name)) for name in archive.namelist()
                                if name.startswith('xl/charts/chart') and name.endswith('.xml')]
                        series=[item for chart in charts for item in chart.findall('.//c:scatterChart/c:ser',NS)
                                if item.findtext('c:tx/c:v',default='',namespaces=NS).startswith('Перепад давления на ')]
                        self.assertEqual([item.findtext('c:tx/c:v',namespaces=NS) for item in series],
                            ['Перепад давления на '+OPTIONAL_TITLES[key] for key in subset])
                        for key,item in zip(subset,series):
                            self.assertEqual([float(point.text) for point in item.findall('c:yVal/c:numRef/c:numCache/c:pt/c:v',NS)],
                                             values[key].tolist())
                    output.seek(0);saved=load_workbook(output)
                    for key in PRESSURE_KEYS:
                        title=OPTIONAL_TITLES[key]
                        if key in subset:
                            self.assertEqual(boundaries[title].tolist(),[f'{values[key].iloc[0]:.1f}',f'{values[key].iloc[-1]:.1f}'])
                        else:
                            self.assertEqual(boundaries[title].tolist(),['',''])
                            self.assertEqual(CalculationApp._format_cell(boundaries[title].iloc[0]),'')
                            if subset:
                                graph=saved['Графики']
                                row=next(row for row in range(42,55) if graph.cell(row,1).value==title+', Па')
                                self.assertIsNone(graph.cell(row,3).value)
                                self.assertIsNone(graph.cell(row,9).value)
                    saved.close()
                    pd.testing.assert_frame_equal(values,before)

    def test_zero_is_available_but_completely_invalid_channel_is_blank(self):
        values,periods=self.fixture(['fso']);values['fso']=0.
        values['fto']=[np.nan,np.inf,-np.inf]
        before=values.copy(deep=True)
        self.assertEqual(pressure_channels(values),['fso'])
        boundaries=build_boundary_table(values,periods)
        self.assertEqual(boundaries['ФСО'].tolist(),['0.0','0.0'])
        self.assertEqual(boundaries['ФТО'].tolist(),['',''])
        pd.testing.assert_frame_equal(values,before)

    def test_missing_reading_of_available_channel_remains_unavailable(self):
        values,periods=self.fixture(['fso']);values.loc[2,'fso']=np.inf
        boundaries=build_boundary_table(values,periods)
        self.assertEqual(boundaries['ФСО'].tolist(),['50.0','—'])
        self.assertTrue(np.isnan(boundaries.attrs['pressure_deltas_pa'][1]['fso_pa']))
        self.assertEqual(boundaries['ФГО'].tolist(),['',''])

    def test_no_boundary_keeps_dashes_only_for_available_channels(self):
        values,periods=self.fixture(['fso']);values['power']=0.
        boundaries=build_boundary_table(values,periods)
        self.assertEqual(boundaries['ФСО'].tolist(),['—','—'])
        self.assertEqual(boundaries['ФТО'].tolist(),['',''])
        self.assertEqual(boundaries['дата'].tolist(),['—','—'])


if __name__=='__main__':unittest.main()
