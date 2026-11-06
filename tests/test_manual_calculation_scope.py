"""Manual dates govern calculations and charts, while Excel keeps full history."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
import datetime

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.utils.datetime import from_excel

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import app
import periods
import workbook_profile as wp
from chart_events import ChartEvent
from data_loader import RECORD_HOURS
from gas_passport import GasPassportHistory
from result_export import save_result_workbook

INTERVALS=[('01-01-2026 00:00','01-01-2026 03:30'),
           ('03-01-2026 00:00','03-01-2026 03:30')]


class DateScopeTests(unittest.TestCase):
    def test_disjoint_intervals_keep_stops_and_lineage_without_gap_rows(self):
        frame=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=9,freq='30min'),
                            'power':[90,0,90,90,5000,90,0,90,90],
                            'hours':np.arange(9)*.5,'excel_row':np.arange(20,29)},index=np.arange(100,109))
        frame.attrs['inlet_pressure_kind']='absolute'
        intervals=[('01-01-2026 00:30','01-01-2026 01:30'),('01-01-2026 02:30','01-01-2026 03:30')]
        before=frame.copy(deep=True)
        selected=periods.select_period_data(frame,intervals)
        self.assertEqual(selected.index.tolist(),[101,102,103,105,106,107])
        self.assertEqual(selected.excel_row.tolist(),[21,22,23,25,26,27])
        self.assertEqual(selected.hours.tolist(),[.5,1.,1.5,2.5,3.,3.5])
        self.assertEqual(int(selected.power.eq(0).sum()),2)
        self.assertEqual(selected.attrs,frame.attrs)
        pd.testing.assert_frame_equal(frame,before)

    def test_overlapping_intervals_do_not_duplicate_and_first_label_wins(self):
        dates=pd.date_range('2026-01-01',periods=5,freq='30min')
        frame=pd.DataFrame({'date':dates,'power':[90]*5})
        intervals=[('01-01-2026 00:00','01-01-2026 01:00'),('01-01-2026 00:30','01-01-2026 02:00')]
        selected=periods.select_period_data(frame,intervals)
        self.assertEqual(len(selected),5)
        self.assertEqual(periods.apply_period_overrides(selected,intervals).period.tolist(),[1,1,1,2,2])
        pd.testing.assert_frame_equal(periods.select_period_data(frame,[]),frame)

    def test_invalid_dates_are_rejected_for_selection_and_labels(self):
        frame=pd.DataFrame({'date':pd.to_datetime(['2026-01-01']),'power':[90]})
        for intervals in [[('bad','01-01-2026')],[('','01-01-2026')],[('02-01-2026','01-01-2026')]]:
            for function in (periods.select_period_data,periods.apply_period_overrides):
                with self.subTest(intervals=intervals,function=function.__name__),self.assertRaises(ValueError):
                    function(frame,intervals)


class Capture:
    def __init__(self,overrides):self.overrides=overrides;self.result=None;self.error=None;self.logs=[]
    def put(self,item):
        kind,value=item
        if kind=='log':self.logs.append(value)
        elif kind=='period_choice':value['overrides']=self.overrides;value['event'].set()
        elif kind=='results':self.result=value
        elif kind=='error':self.error=value


class ManualWorkerScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'Ижевская ГТ-1.xlsx'
        self.addCleanup(plt.close,'all')
        self.old_overrides=periods.PERIOD_OVERRIDES
        self.addCleanup(setattr,periods,'PERIOD_OVERRIDES',self.old_overrides)
        book=Workbook();sheet=book.active;sheet.title='Данные'
        sheet.append(['Дата','Тнк, °C','Ткк, °C','Pатм, Па','Pнк, мбар','Ркк, бар',
                      'ВНА','N, МВт','Nприв, МВт','Bприв, нм3/ч','bприв','ηoi_Cprop',
                      'ВЛО, Па','ФГО+ФТО, Па','Наработка'])
        self.dates=pd.DatetimeIndex([date for day in range(1,4) for date in
                    pd.date_range(f'2026-01-{day:02d}',periods=8,freq='30min')])
        for index,date in enumerate(self.dates):
            outside=date.day==2;power=5000. if outside else 80.+index/10
            if index==2:power=0.
            sheet.append([date.to_pydatetime(),20.,300.,101000.,1000.,10.,85.,power,power,
                          10000.+power*20,200.,84.,99999. if outside else 200.+index,220.,1000.+index*.5])
        book.save(self.path)
        with patch.object(wp,'profile_path',return_value=self.root/'profiles.json'):
            layout=wp.read_layout(self.path)
            self.setup=wp.confirm(layout,'izhevsk_tec','1',wp.suggestions(layout,'izhevsk_tec','1'),save=False)

    def calculate(self,overrides,passport=None):
        capture=Capture(overrides)
        runner=SimpleNamespace(output_queue=capture,station_repository=app.get_station_repository(),
                               _build_vna_overview=app.CalculationApp._build_vna_overview)
        events=tuple(ChartEvent(datetime.datetime(2026,1,day,1),'Событие') for day in (1,2,3))
        with patch('app.resolve_passport',return_value=passport):
            app.CalculationApp._calculation_worker(runner,self.path,None,'',None,1.,2.,1.,events,'izhevsk_tec','1',self.setup)
        self.assertIsNone(capture.error,str(capture.error)+'\n'+''.join(capture.logs)[-5000:])
        self.assertIsNotNone(capture.result)
        return capture.result

    def test_every_result_uses_manual_union_and_excel_keeps_history(self):
        result=self.calculate(INTERVALS);snapshot=result['snapshot']
        chart=snapshot.pressure_chart
        expected=self.dates[self.dates.day.isin([1,3])]
        self.assertEqual(pd.DatetimeIndex(chart.values.date).tolist(),expected.tolist())
        self.assertEqual(int(chart.values.power.eq(0).sum()),1)
        self.assertEqual(chart.degradation_values.date.tolist(),expected.tolist())
        self.assertEqual(len(chart.rh_values),15)
        self.assertTrue(periods.period_selection_mask(chart.rh_values.date,INTERVALS).all())
        self.assertEqual([e.date.day for e in chart.events],[1,3])
        self.assertEqual(result['vna_periods'].period.tolist(),[1,2])
        plotted=pd.DatetimeIndex(result['pressure_figure'].axes[0].lines[0].get_xdata())
        self.assertEqual(plotted.tolist(),expected.tolist())
        self.assertEqual(snapshot.report_data['source']['data_start_date'],'01.01.2026')
        self.assertEqual(snapshot.report_data['source']['data_end_date'],'03.01.2026')
        self.assertEqual(snapshot.report_data['source']['selection_mode'],'manual')
        self.assertEqual(len(snapshot.report_data['source']['selected_intervals']),2)
        self.assertEqual(snapshot.report_data['summary']['total_operating_hours'],'8')
        self.assertEqual(snapshot.report_data['summary']['calculated_total_hours'],'7,5')
        frame=snapshot.data.as_headered_frame()
        self.assertEqual(len(frame),24)
        self.assertEqual(frame.iloc[:,14].tolist(),[1000.+i*.5 for i in range(24)])
        tables=dict(snapshot.sections)
        self.assertEqual(tables['Наработка и пороги'].iloc[0]['Часы ВНА выше 80 %'],15*RECORD_HOURS)
        path=self.root/'selected.xlsx'
        save_result_workbook(snapshot.data,snapshot.sections,path,pressure_chart=chart,book_profile=snapshot.book_profile)
        exported=load_workbook(path,data_only=True)
        self.addCleanup(exported.close)
        self.assertEqual(exported['Данные'].max_row,25)
        points=exported['Графики']._charts[0].series[0].xVal.numRef.numCache.pt
        self.assertEqual([pd.Timestamp(from_excel(float(point.v))) for point in points],expected.tolist())

    def test_ready_book_gas_passports_need_cover_only_selected_dates(self):
        entries=[dict(station_id='izhevsk_tec',unit='1',density_kg_per_nm3=.7,
                      q_lower_mj_per_nm3=35.,carbon_hydrogen_ratio=3.,
                      valid_from=f'2026-01-{day:02d}',valid_until=f'2026-01-{day+1:02d}') for day in (1,3)]
        passport=GasPassportHistory.from_dict(dict(station_id='izhevsk_tec',unit='1',entries=entries))
        result=self.calculate(INTERVALS,passport=passport)
        self.assertEqual(len(result['snapshot'].pressure_chart.degradation_values),16)

    def test_automatic_mode_keeps_full_scope_and_counter_reporting(self):
        result=self.calculate(None);snapshot=result['snapshot']
        self.assertEqual(len(snapshot.pressure_chart.values),24)
        self.assertEqual([e.date.day for e in snapshot.pressure_chart.events],[1,2,3])
        self.assertNotIn('selection_mode',snapshot.report_data['source'])
        self.assertEqual(snapshot.report_data['summary']['total_operating_hours'],'1011,5')
        self.assertEqual(len(snapshot.data.as_headered_frame()),24)

    def test_manual_bounds_with_no_data_return_clear_error(self):
        capture=Capture([('01-01-2020','02-01-2020')])
        runner=SimpleNamespace(output_queue=capture,station_repository=app.get_station_repository(),
                               _build_vna_overview=app.CalculationApp._build_vna_overview)
        with patch('app.resolve_passport',return_value=None):
            app.CalculationApp._calculation_worker(runner,self.path,None,'',None,1.,2.,1.,(),'izhevsk_tec','1',self.setup)
        self.assertIsNone(capture.result)
        self.assertIn('В выбранных интервалах нет данных',str(capture.error))
