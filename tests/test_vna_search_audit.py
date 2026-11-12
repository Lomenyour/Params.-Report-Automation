"""Audit the legacy maximum-date-span search against direct decimal windows."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scr'))
from VNA_full import _find_flexible_vna_intervals


def exhaustive(values):
    data = values.loc[values.vna.ge(0) & values.vna.lt(100)].sort_values('date').reset_index(drop=True)
    windows = {}
    if data.empty:
        return windows, data
    for width in range(1, 11):
        first = max(0, int(np.floor(data.vna.min()*10))-1)
        last = min(1000-width, int(np.ceil(data.vna.max()*10)))
        for lower in range(first, last+1):
            rows = tuple(np.flatnonzero(data.vna.ge(lower/10) & data.vna.lt((lower+width)/10)))
            if not rows or rows in windows:
                continue
            pairs = []
            for position, i in enumerate(rows):
                a = data.iloc[i]
                for j in rows[position+1:]:
                    b = data.iloc[j]
                    if (np.isfinite([a.eta_compressor,b.eta_compressor]).all() and
                        round(abs(a.t-b.t),12)<=.5 and round(abs(a.p-b.p),12)<=5 and
                        round(abs(a.eta_compressor-b.eta_compressor),12)<.8):
                        pairs.append((-int((b.date-a.date).value),i,j))
            if pairs:
                _, i, j = min(pairs)
                windows[rows] = (lower/10,(lower+width)/10,i,j)
    return windows, data


class LegacySearchAuditTest(unittest.TestCase):
    def test_direct_windows_and_exhaustive_pairs_including_decimal_edges(self):
        rng=np.random.default_rng(121126)
        for sample in range(55):
            n=13
            data=pd.DataFrame(dict(date=pd.Timestamp('2026-01-01')+pd.to_timedelta(rng.integers(0,50,n),unit='h'),
                vna=86+rng.integers(0,12,n)/10, t=15.6+rng.integers(0,4,n)*.25,
                p=990+rng.integers(0,4,n)*2.5, eta_compressor=80+rng.integers(0,5,n)*.2,
                pi_k=13., tkk=np.arange(n,dtype=float)))
            if sample%5==0:
                data.loc[0,'eta_compressor']=np.nan
            expected, ordered=exhaustive(data)
            actual={}
            for pair in _find_flexible_vna_intervals(data):
                rows=tuple(np.flatnonzero(ordered.vna.ge(pair['vna_from']) & ordered.vna.lt(pair['vna_to'])))
                indices=(int(np.flatnonzero(ordered.tkk.eq(pair['tkk_1']))[0]),
                         int(np.flatnonzero(ordered.tkk.eq(pair['tkk_2']))[0]))
                # The old method promises maximum span, not a new tie-break
                # among different measurements sharing the same timestamp.
                i,j=indices
                actual[rows]=(pair['vna_from'],pair['vna_to'],int((ordered.date.iloc[j]-ordered.date.iloc[i]).value))
                self.assertIn(i,rows)
                self.assertIn(j,rows)
                a,b=ordered.iloc[i],ordered.iloc[j]
                self.assertLessEqual(round(abs(a.t-b.t),12),.5)
                self.assertLessEqual(round(abs(a.p-b.p),12),5)
                self.assertLess(round(abs(a.eta_compressor-b.eta_compressor),12),.8)
                self.assertEqual(pair['count'],len(rows))
            expected={rows:(lower,upper,int((ordered.date.iloc[j]-ordered.date.iloc[i]).value))
                      for rows,(lower,upper,i,j) in expected.items()}
            with self.subTest(sample=sample):
                self.assertEqual(actual,expected)

    def test_right_open_upper_edge_and_inclusive_temperature_limit(self):
        data=pd.DataFrame(dict(date=pd.date_range('2026-01-01',periods=3),
            vna=[86.1,86.1,100.],t=[15.6,16.1,15.6],p=990.,
            eta_compressor=80.,pi_k=13.,tkk=[370.,371.,372.]))
        result=_find_flexible_vna_intervals(data)
        self.assertEqual(len(result),1)
        pair=result[0]
        self.assertEqual(pair['vna_interval'],'86.1-86.2')
        self.assertEqual((pair['count'],pair['date_2']),(2,data.date.iloc[1]))
        self.assertAlmostEqual(pair['share_percent'],200/3)
        self.assertEqual(_find_flexible_vna_intervals(data.assign(vna=100.)),[])


if __name__=='__main__':
    unittest.main()
