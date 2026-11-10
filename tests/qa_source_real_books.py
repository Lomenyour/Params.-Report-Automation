"""Append two sensor records to copies of real books; never run analytics."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile
import olefile

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scr'))
from data_assembly import SensorMapping
from source_workbook import save_source_workbook
from station_profiles import get_station_repository
from workbook_profile import BookSetup, read_layout, suggestions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=int,choices=(0,1),required=True)
    args=parser.parse_args()
    filename,station,unit=(('Ижевская ГТ-1 2 квартал 2026.xlsx','izhevsk_tec','1'),
                           ('СызТЭЦ ГТ-10 2кв 2026.xlsm','syz_tec','10'))[args.index]
    folder=ROOT/'data/qa_source_real_20261110'/str(args.index)
    folder.mkdir(parents=True,exist_ok=True)
    book=ROOT/'data'/filename
    before=hashlib.sha256(book.read_bytes()).hexdigest()
    layout=read_layout(book)
    columns=suggestions(layout,station,unit)
    stat=book.stat()
    setup=BookSetup(station,unit,columns,{}, {},(str(book.resolve()),stat.st_mtime_ns,stat.st_size),layout.header_row)
    date_col=setup.bindings['date']['column']
    dates=pd.to_datetime(layout.values[date_col],errors='coerce')
    last=int(dates.last_valid_index());date=dates.iloc[last]
    targets=list(dict.fromkeys(setup.sensor_columns.values()))
    mappings=[SensorMapping(f'TEST_{col}',col) for col in targets]
    values=[layout.values.at[last,col] for col in targets]
    raw=folder/'append.csv'
    with raw.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.writer(handle,delimiter=';')
        writer.writerow(['date','time',*[item.source for item in mappings]])
        for offset in (0,1,2):
            stamp=date+pd.Timedelta(minutes=30*offset)
            writer.writerow([stamp.strftime('%Y-%m-%d'),stamp.strftime('%H:%M:%S'),
                             *['' if pd.isna(value) else value for value in values]])
    destination=folder/('updated'+book.suffix)
    started=time.monotonic()
    response=save_source_workbook(book,raw,'CSV',mappings,destination,setup=setup,
        station_id=station,unit=unit,repository=get_station_repository(),log=lambda text:print(text,flush=True))
    assert hashlib.sha256(book.read_bytes()).hexdigest()==before
    # Original VBA, pictures, chart parts and all sheet names must survive Excel's
    # own save. XML serialization may differ, so compare package inventory here.
    with zipfile.ZipFile(book) as original,zipfile.ZipFile(destination) as updated:
        original_names=set(original.namelist());updated_names=set(updated.namelist())
        assert len([x for x in updated_names if x.startswith('xl/worksheets/sheet') and x.endswith('.xml')])==len(
            [x for x in original_names if x.startswith('xl/worksheets/sheet') and x.endswith('.xml')])
        for name in original_names:
            if name.endswith('vbaProject.bin'):
                # Excel may change OLE directory timestamps on save. Every VBA
                # stream, including source and compiled code, must remain exact.
                with olefile.OleFileIO(io.BytesIO(original.read(name))) as first, \
                     olefile.OleFileIO(io.BytesIO(updated.read(name))) as second:
                    assert first.listdir()==second.listdir(),'VBA stream list changed'
                    for stream in first.listdir():
                        assert first.openstream(stream).read()==second.openstream(stream).read(),stream
    result=dict(response=response,seconds=round(time.monotonic()-started,2),input_preserved=True,
                original_sheets=len([x for x in original_names if x.startswith('xl/worksheets/sheet') and x.endswith('.xml')]))
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS:',filename,'seconds',result['seconds'],'formula columns',response['formula_columns'],
          'formula errors',response['formula_error_count'])


if __name__=='__main__':main()
