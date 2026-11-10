"""End-to-end source-book check using an isolated installed Excel instance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scr'))
from data_assembly import SensorMapping
from source_workbook import save_source_workbook
from station_profiles import get_station_repository
from workbook_profile import BookSetup, read_layout


def main():
    folder=ROOT/'data/qa_source_workbook_20261110'
    folder.mkdir(parents=True,exist_ok=True)
    helper=ROOT/'tests/qa_source_workbook_excel.ps1'
    def excel(mode):
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(helper),
                        '-Mode',mode,'-Folder',str(folder)],check=True)
    excel('create')
    raw=folder/'raw.csv'
    raw.write_text('date;time;CH;TEXT\n2025-12-31;23:30:00;19;before\n'
        '2026-01-01;00:00:00;20;overlap\n2026-01-01;01:00:00;22;insert\n'
        '2026-01-01;03:30:00;0;zero\n2026-01-01;04:00:00;24;=1+1\n'
        '2026-01-01;04:01:00;999;skip\n',encoding='utf-8-sig')
    results={}
    for extension in ('xlsx','xlsm'):
        book=folder/f'original.{extension}'
        before=hashlib.sha256(book.read_bytes()).hexdigest()
        layout=read_layout(book)
        roles=dict(A='hours_input',B='date',C='power')
        columns=[dict(column=col,header=header,role=roles.get(col,''),
                      unit='МВт' if col=='C' else '',
                      kind='service' if col in ('A','B') else 'measured' if col in ('C','G','J') else 'computed')
                 for col,header in layout.headers.items()]
        stat=book.stat()
        setup=BookSetup('izhevsk_tec','1',columns,{}, {},(str(book.resolve()),stat.st_mtime_ns,stat.st_size))
        results[extension]=save_source_workbook(book,raw,'CSV',
            [SensorMapping('CH','C'),SensorMapping('TEXT','J')],folder/f'updated.{extension}',
            setup=setup,station_id='izhevsk_tec',unit='1',repository=get_station_repository(),log=print)
        assert hashlib.sha256(book.read_bytes()).hexdigest()==before
        assert results[extension]['formula_error_count']==1,results[extension]
    excel('verify')
    (folder/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: original input hashes unchanged; analytics not invoked')


if __name__=='__main__':main()
