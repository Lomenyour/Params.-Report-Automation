"""Compare legacy candidates with a recorded Git version on non-boundary inputs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scr'))
import VNA_full


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='f6bb96e')
    parser.add_argument('--output',type=Path,default=ROOT/'build_test/vna_algorithm2_qa_20261112/legacy_comparison.json')
    args=parser.parse_args()
    legacy=types.ModuleType('legacy_vna')
    source=subprocess.check_output(['git','show',f'{args.baseline}:scr/VNA_full.py'],cwd=ROOT)
    exec(compile(source,'baseline_VNA_full.py','exec'),legacy.__dict__)
    rng=np.random.default_rng(17812)
    count=0
    for sample in range(20):
        n=30
        data=pd.DataFrame(dict(date=pd.date_range('2026-01-01',periods=n,freq='30min'),
            vna=86+rng.integers(0,16,n)/10+.01,t=rng.normal(10,1,n),p=rng.normal(990,3,n),
            eta_compressor=rng.normal(80,.4,n),pi_k=13.,tkk=370.))
        tables=[]
        for module in (legacy,VNA_full):
            table=pd.DataFrame(module._find_flexible_vna_intervals(data)).drop(
                columns=['vna_from','vna_to'],errors='ignore')
            numeric=table.select_dtypes(include='number').columns
            table[numeric]=table[numeric].round(3)
            tables.append(table)
        pd.testing.assert_frame_equal(*tables)
        count+=len(tables[0])
    report=dict(baseline=args.baseline,seed=17812,samples=20,identical_candidates=count,
        conditions='Non-boundary finite inputs; all output fields after report rounding')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'PASS: {count} identical candidates in 20 samples against {args.baseline}')


if __name__=='__main__':
    main()
