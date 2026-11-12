"""Independent exhaustive oracle for density selection; no optimized search helpers."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from vna_density import density_period_top10
from compressor_degradation_chart import prepare_compressor_plots


def exhaustive(values, start, end):
    data = values.sort_values('date', kind='stable').reset_index(drop=True)
    duration = int((end-start).value)
    windows = {}
    for width in range(1, 11):
        low = max(0, int(np.floor(data.vna.min()*10))-10)
        high = min(1000-width, int(np.ceil(data.vna.max()*10))+1)
        for left in range(low, high+1):
            rows = tuple(np.flatnonzero(data.vna.ge(left/10) & data.vna.lt((left+width)/10)))
            if rows and rows not in windows:
                windows[rows] = (width, left)
    top = {}
    for rows, (width, left) in windows.items():
        best = None
        for position, i in enumerate(rows):
            a = data.iloc[i]
            for j in rows[position+1:]:
                b = data.iloc[j]
                if not np.isfinite([a.t,a.p,a.eta_compressor,a.pi_k,
                                    b.t,b.p,b.eta_compressor,b.pi_k]).all():
                    continue
                span = int((b.date-a.date).value)
                eta = abs(b.eta_compressor-a.eta_compressor)
                if (span*3 < duration*2 or round(abs(b.t-a.t),12)>.5 or
                    round(abs(b.p-a.p),12)>5 or round(eta,12)>=.8):
                    continue
                selected = data.loc[data.vna.ge(left/10) & data.vna.lt((left+width)/10) &
                    data.t.round(3).between(min(round(a.t,3),round(b.t,3)),max(round(a.t,3),round(b.t,3))) &
                    data.p.round(3).between(min(round(a.p,3),round(b.p,3)),max(round(a.p,3),round(b.p,3))) &
                    data.eta_compressor.round(3).between(min(round(a.eta_compressor,3),round(b.eta_compressor,3)),
                                                       max(round(a.eta_compressor,3),round(b.eta_compressor,3))) &
                    data.date.notna() & np.isfinite(data.pi_k) & np.isfinite(data.eta_compressor)]
                score = (len(selected), span, -eta, -i, -j)
                item = dict(score=score,i=i,j=j,rows=tuple(selected.excel_row),width=width,left=left,
                            count=len(rows))
                if best is None or score > best['score']:
                    best = item
        if best is not None:
            score = best['score']
            best['score'] = (*score[:3],-width,-left,*score[3:])
            if best['rows'] not in top or best['score']>top[best['rows']]['score']:
                top[best['rows']] = best
    return sorted(top.values(),key=lambda item:item['score'],reverse=True)[:10],data


def fixture(count=9):
    return pd.DataFrame({'date':pd.date_range('2026-01-01',periods=count,freq='1D'),
        'period':1,'vna':86.21,'t':10.,'p':990.,'eta_compressor':80.,
        'pi_k':13.+np.arange(count)/100,'tkk':370.+np.arange(count)/100,
        'excel_row':np.arange(count)+2})


class DensitySearchTest(unittest.TestCase):
    def assert_oracle(self,data,start=None,end=None):
        start = data.date.min() if start is None else start
        end = data.date.max() if end is None else end
        before=data.copy(deep=True)
        expected,ordered=exhaustive(data,start,end)
        table=density_period_top10(data,1,start,end)
        self.assertEqual(len(table),len(expected))
        periods=pd.DataFrame([dict(period=1,date_start=start,date_end=end)])
        for (_,row),item in zip(table.iterrows(),expected):
            self.assertEqual(row.vna_interval,f'{item["left"]/10:.1f}-{(item["left"]+item["width"])/10:.1f}')
            self.assertEqual(row.plot_points,len(item['rows']))
            self.assertEqual(row['count'],item['count'])
            self.assertEqual(row.date_1,ordered.iloc[item['i']].date)
            self.assertEqual(row.date_2,ordered.iloc[item['j']].date)
            self.assertEqual(row.tkk_1,round(ordered.iloc[item['i']].tkk,3))
            plot=prepare_compressor_plots(data,periods,[table],{1:int(row['rank'])})[0]
            self.assertEqual(tuple(plot.points.excel_row),item['rows'])
        pd.testing.assert_frame_equal(data,before)
        return table

    def test_matches_exhaustive_search_with_boundaries_and_overlapping_windows(self):
        rng=np.random.default_rng(11212)
        for sample in range(45):
            data=fixture(8)
            data['vna']=86+rng.integers(0,14,len(data))/10
            data['t']=10+rng.integers(0,5,len(data))*.2
            data['p']=990+rng.integers(0,5,len(data))*2
            data['eta_compressor']=80+rng.integers(0,8,len(data))*.1
            if sample%3==0:data.loc[3,'eta_compressor']=np.nan
            with self.subTest(sample=sample):self.assert_oracle(data)

    def test_duplicate_groups_preserve_optimal_dates_and_first_tie(self):
        data=fixture(12)
        data.loc[1,'date']=data.loc[0,'date']
        data.loc[10,'date']=data.loc[11,'date']
        table=self.assert_oracle(data)
        self.assertEqual(len(table),1)
        self.assertEqual(table.iloc[0].plot_points,12)
        self.assertEqual(table.iloc[0].tkk_1,370.)
        self.assertEqual(table.iloc[0].tkk_2,370.1)

    def test_more_plotted_points_can_beat_longest_pair(self):
        data=fixture(6)
        data['date']=pd.Timestamp('2026-01-01')+pd.to_timedelta([0,1,2,3,4,6],unit='D')
        offsets=np.array([.2,0.,.1,.3,.4,.2])
        data['t']=10+offsets;data['p']=990+offsets;data['eta_compressor']=80+offsets
        table=self.assert_oracle(data)
        self.assertEqual(table.iloc[0].plot_points,4)
        self.assertEqual(table.iloc[0].delta_days,5.)
        self.assertEqual(table.iloc[0].date_1,pd.Timestamp('2026-01-02'))

    def test_top10_cutoff_matches_all_windows(self):
        rng=np.random.default_rng(901)
        data=fixture(24)
        data['vna']=86+rng.integers(0,15,len(data))/10+.01
        data['t']=10+rng.uniform(0,.5,len(data))
        data['p']=990+rng.uniform(0,5,len(data))
        data['eta_compressor']=80+rng.uniform(0,.79,len(data))
        table=self.assert_oracle(data)
        self.assertEqual(len(table),10)

    def test_minimum_span_uses_full_period_and_is_inclusive(self):
        data=fixture(3)
        start=data.date.min();end=start+pd.Timedelta(days=3)
        self.assertFalse(self.assert_oracle(data,start,end).empty)
        end+=pd.Timedelta(nanoseconds=1)
        self.assertTrue(self.assert_oracle(data,start,end).empty)

    def test_finite_plot_requirements_and_decimal_tolerance_edges(self):
        data=fixture(6)
        data['t']=[15.6,15.7,15.8,15.9,16.,16.1]
        data.loc[2,'pi_k']=np.inf
        data.loc[3,'eta_compressor']=np.nan
        data['vna']=86.1
        table=self.assert_oracle(data)
        self.assertEqual(table.iloc[0].plot_points,4)
        self.assertTrue((table.delta_t<=.5).all())

    def test_empty_result_never_uses_first_algorithm_as_fallback(self):
        data=fixture(6);data['eta_compressor']=[80.,80.,80.,82.,82.,82.]
        result=self.assert_oracle(data)
        self.assertTrue(result.empty)
        self.assertIn('2/3',result.attrs['empty_reason'])
