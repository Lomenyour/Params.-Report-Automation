"""Export deterministic period economics to Excel and a Word input snapshot."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scr'),str(ROOT/'tests')]
from test_period_economics import fixture,calculate
from reporting import build_report_data,save_report_data
from result_export import DataSheetValues,save_result_workbook


def main():
    output=ROOT/'build_test/period_economics_qa_20261112'
    output.mkdir(parents=True,exist_ok=True)
    parts=[]
    for number,n,vna in ((1,105.,94.2),(2,95.,91.2)):
        part=fixture(5);part['period']=number;part['date']+=pd.Timedelta(days=number*3)
        part['power']=n-10*np.arange(5)*.5;part['vna']=vna
        part.loc[3 if number==1 else 2,'vna']=80.
        parts.append(part)
    data=pd.concat(parts,ignore_index=True)
    result=calculate(data)
    assert result['annualization_hours']=={'underproduction':3.,'fuel':3.}
    assert abs(result['annualized']['underproduction_mwh']-51100)<1e-7
    assert abs(result['annualized']['fuel_overrun_nm3']-905200)<1e-6
    raw=pd.DataFrame([['Дата','Nприв','bприв','ВНА','Перерасход',None,'Недовыработка',None]]+
        [[r.date,r.power,r.fuel_specific,r.vna,-1.,-1.,-1.,-1.] for r in data.itertuples()])
    book=DataSheetValues(raw,0)
    book.apply_economic_result(result,'A')
    path=output/'synthetic_economics.xlsx'
    save_result_workbook(book,[('Экономика',result['table'])],path)
    saved=load_workbook(path,data_only=True)
    try:
        sheet=saved['Данные']
        assert abs(sum(sheet.cell(i,6).value or 0 for i in range(2,12))-310)<1e-7
        assert abs(sum(sheet.cell(i,8).value or 0 for i in range(2,12))-17.5)<1e-8
    finally:saved.close()
    periods=pd.DataFrame([dict(period=n,date_start=p.date.min(),date_end=p.date.max()) for n,p in data.groupby('period')])
    context=build_report_data(source_data=data,rh_data=data,periods_df=periods,boundary_table=None,
        delta_table=None,vna_results=[],economics_result=result,nominal_hours={'power_threshold':999},
        gas_tariff=2.,electricity_tariff=100.,electricity_cost=20.,
        station={'name':'Контрольная ТЭЦ','name_genitive':'Контрольной ТЭЦ'},
        turbine={'name':'ГТУ-1','number':'1','model':'Контрольная модель'})
    save_report_data(context,output/'synthetic_context.json')
    summary=dict(local_thresholds=context['economics']['periods'],hours=result['annualization_hours'],
                 annualized=result['annualized'],excel_contributions_match=True)
    (output/'report_checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: local 94/91 % thresholds, 3 eligible hours, manual annual results, Excel row contributions and Word JSON')


if __name__=='__main__':main()
