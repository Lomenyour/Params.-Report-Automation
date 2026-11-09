"""Recalculate saved inputs with the previous/current RH, compare unaffected results."""
import argparse
import contextlib
from dataclasses import replace
import json
from pathlib import Path
import pickle
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scr'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
import periods
import RH_raschet as current
from rh_chart import prepare_rh_plots, add_rh_charts
from rh_display import dirty_above_clean, power_bounds


def previous_rh():
    source = subprocess.check_output(['git','show','5ed1149:scr/RH_raschet.py'],
                                    cwd=ROOT, text=True, encoding='utf-8')
    namespace = {'__name__':'rh_baseline', '__file__':str(ROOT/'scr/RH_raschet.py')}
    exec(compile(source, namespace['__file__'], 'exec'), namespace)
    return namespace['main']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline = previous_rh()
    reports = []
    for path in args.snapshot:
        snapshot = pickle.loads(path.read_bytes())
        unchanged = pickle.dumps(snapshot)
        chart = snapshot.pressure_chart
        name = path.parent.name
        overrides = periods.PERIOD_OVERRIDES
        periods.PERIOD_OVERRIDES = [(row.date_start,row.date_end)
                                   for row in chart.periods.itertuples(index=False)]
        try:
            calculated = []
            tables = []
            for label, function in (('baseline',baseline),('current',current.main)):
                output = {}
                with (args.output/f'{name}_{label}.log').open('w',encoding='utf-8') as log:
                    with contextlib.redirect_stdout(log):
                        result = function(data=chart.values.copy(deep=True), show_plots=False,
                                          vna_data=chart.degradation_values, output_tables=output)
                calculated.append(result)
                tables.append(output)
                print(f'{name}: {label} calculation completed',flush=True)
        finally:
            periods.PERIOD_OVERRIDES = overrides
        old, new = calculated
        pd.testing.assert_frame_equal(old[0],new[0])
        pd.testing.assert_frame_equal(old[1],new[1])
        assert tables[0].keys() == tables[1].keys()
        for key in tables[0]:
            pd.testing.assert_frame_equal(tables[0][key],tables[1][key])
        assert len(old[3]) == len(new[3])
        for first,second in zip(old[3],new[3],strict=True):
            pd.testing.assert_frame_equal(first,second[first.columns])
        assert len(new[2]) == len({row['period'] for row in old[2]})
        plots = prepare_rh_plots(new[0],new[2])
        assert [p.result['rank'] for p in plots] == [r['rank'] for r in new[2]]
        selected = []
        for result in new[2]:
            number = result['period']
            bounds = power_bounds(new[0],result)
            np.testing.assert_array_equal(bounds,[result['power_min'],result['power_max']])
            assert bool(dirty_above_clean(result,bounds)) == result['preferred'] or result['candidate_count']==0
            if not result['preferred']:
                first = next(r for r in old[2] if r['period']==number)
                for key in ('k_start','k_end','b_start','b_end','start_window_id','end_window_id'):
                    assert result[key] == first[key], (path,number,key)
            selected.append(dict(period=int(number),rank=int(result['rank']),
                candidate_count=result['candidate_count'],preferred=result['preferred'],
                power_min=bounds[0],power_max=bounds[1],b_end_lower=result['b_end']<result['b_start']))
        figure = current.plot_selected_windows(new[0],new[2],show=False)
        figure.savefig(args.output/f'{name}_gui.png',dpi=130)
        plt.close(figure)
        book = Workbook(write_only=True)
        sheet = book.create_sheet('Графики')
        for column in range(1,48):
            sheet.column_dimensions[get_column_letter(column)].width = 9.5
        cells,bottom = add_rh_charts(sheet,plots,1)
        for row in range(1,bottom+1):
            record = cells.get(row,{})
            sheet.append([record.get(c,(None,None))[0] for c in range(1,max(record,default=0)+1)])
        book.save(args.output/f'{name}.xlsx')
        assert pickle.dumps(snapshot)==unchanged, 'Saved snapshot was modified'
        report = dict(snapshot=str(path),unaffected_results_match=True,snapshot_unchanged=True,selected=selected)
        reports.append(report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
    (args.output/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
