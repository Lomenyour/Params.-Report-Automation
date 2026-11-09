"""Opt-in RH presentation checks from unchanged saved local snapshots."""
import argparse
import ast
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
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from rh_chart import prepare_rh_plots, add_rh_charts
from rh_display import power_bounds, dirty_above_clean
from RH_raschet import plot_selected_windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    old_source = subprocess.check_output(['git','show','d0a77d1:scr/RH_raschet.py'],
                                       cwd=ROOT, text=True, encoding='utf-8')
    old_function = next(node for node in ast.parse(old_source).body
                        if isinstance(node,ast.FunctionDef) and node.name=='select_rh_variants')
    namespace = {'np':np}
    exec(compile(ast.Module(body=[old_function],type_ignores=[]),'old_selector.py','exec'), namespace)
    reports = []
    for path in args.snapshot:
        snapshot = pickle.loads(path.read_bytes())
        before = pickle.dumps(snapshot)
        values, candidates = snapshot.pressure_chart.rh_values, snapshot.pressure_chart.rh_results
        old = {row['period']:row['rank'] for row in namespace['select_rh_variants'](candidates)}
        plots = prepare_rh_plots(values, candidates)
        figure = plot_selected_windows(values, candidates, show=False)
        if figure is not None:
            figure.savefig(args.output/f'{path.parent.name}_gui.png',dpi=130)
            plt.close(figure)
        book = Workbook(write_only=True)
        sheet = book.create_sheet('Графики')
        for index in range(1,48):
            sheet.column_dimensions[get_column_letter(index)].width = 9.5
        cells, bottom = add_rh_charts(sheet, plots, 1)
        for row in range(1,bottom+1):
            record = cells.get(row,{})
            sheet.append([record.get(c,(None,None))[0] for c in range(1,max(record,default=0)+1)])
        for chart, plot in zip(sheet._charts,plots,strict=True):
            arrows = [s for s in chart.series if s.tx.v=='Стрелка состояния']
            vectors = []
            bounds = power_bounds(values,plot.result)
            for series,prefix in zip(arrows,('end','start')):
                x = [p.v for p in series.xVal.numLit.pt]
                y = [p.v for p in series.yVal.numLit.pt]
                assert bounds[0]-1e-8 <= x[-1] <= bounds[1]+1e-8, (path,plot.result['period'],prefix,x,bounds)
                assert abs(y[-1]-(plot.result[f'k_{prefix}']*x[-1]+plot.result[f'b_{prefix}']))<1e-7
                vectors.append(np.array([x[-1]-x[0],y[-1]-y[0]]))
            cross = vectors[0][0]*vectors[1][1]-vectors[0][1]*vectors[1][0]
            assert abs(cross) <= 1e-8 * max(1.,np.linalg.norm(vectors[0])*np.linalg.norm(vectors[1]))
        book.save(args.output/f'{path.parent.name}.xlsx')
        assert pickle.dumps(snapshot)==before, 'Presentation changed snapshot or candidates'
        report = dict(snapshot=str(path),snapshot_unchanged=True,periods=[
            dict(period=p.result['period'],old_rank=old[p.result['period']],rank=p.result['rank'],
                 preferred=dirty_above_clean(p.result,power_bounds(values,p.result))) for p in plots])
        reports.append(report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
    (args.output/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
