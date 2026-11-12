"""Independent expected row contributions and period-specific annualization."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from economics import calculate_economics, POWER_HOURS, FUEL_HOURS
from data_assembly import AssembledData, apply_economic_columns


def fixture(n=4):
    tau=np.arange(n)*.5
    return pd.DataFrame(dict(date=pd.date_range('2026-01-01',periods=n,freq='30min'),
        period=1,hours=100+tau,power=100-tau,fuel_specific=300+2*tau,
        vna=86.5,ambient_temperature=20.))


def calculate(data, **kwargs):
    periods=pd.DataFrame([dict(period=number,date_start=part.date.min(),date_end=part.date.max())
                          for number,part in data.groupby('period')])
    return calculate_economics(data,periods,gas_price_rub_per_m3=2.,
        electricity_price_rub_per_mwh=100.,electricity_cost_rub_per_mwh=20.,
        power_threshold=999.,vna_data=data,**kwargs)


class PeriodEconomicsTest(unittest.TestCase):
    def test_rows_odd_tail_and_excel_contributions_are_not_lost(self):
        data=fixture(5);before=data.copy(deep=True)
        result=calculate(data);p=result['periods'][0];rows=result['row_losses']
        np.testing.assert_allclose(rows.power_loss_rate,[0,.5,1,1.5,2],atol=1e-9)
        np.testing.assert_allclose(rows.fuel_loss_rate,[0,99.5,198,295.5,392],atol=1e-8)
        self.assertAlmostEqual(p['Недовыработка, МВт·ч'],2.5)
        self.assertAlmostEqual(p['Перерасход, нм³'],492.5)
        self.assertEqual((p[POWER_HOURS],p[FUEL_HOURS]),(2.5,2.5))
        frame=pd.DataFrame(dict(A=data.date,E=-1.,F=-1.,G=-1.,H=-1.),index=pd.DatetimeIndex(data.date))
        assembled=AssembledData(frame,dict(A='Дата',E='Перерасход',F=None,G='Недовыработка',H=None),0,0,{},[])
        apply_economic_columns(assembled,result)
        self.assertAlmostEqual(frame.F.sum(),492.5)
        self.assertAlmostEqual(frame.H.sum(),2.5)
        self.assertAlmostEqual(frame.F.iloc[-1],196)
        pd.testing.assert_frame_equal(data,before)

    def test_local_threshold_intersections_and_actual_denominator(self):
        parts=[]
        for number,n_start,vna in ((1,105.,94.2),(2,95.,91.2)):
            d=fixture(5);tau=np.arange(5)*.5
            d['period']=number;d['date']+=pd.Timedelta(days=number*3)
            d['power']=n_start-10*tau;d['vna']=vna
            d.loc[3 if number==1 else 2,'vna']=80.
            parts.append(d)
        result=calculate(pd.concat(parts,ignore_index=True))
        self.assertEqual([p['Порог Nприв, МВт'] for p in result['periods']],[90.,80.])
        self.assertEqual([p['Порог ВНА, %'] for p in result['periods']],[94.,91.])
        self.assertEqual([p[POWER_HOURS] for p in result['periods']],[1.5,1.5])
        self.assertEqual(result['annualization_hours'],{'underproduction':3.,'fuel':3.})
        self.assertAlmostEqual(result['annualized']['underproduction_mwh'],51100.)
        self.assertAlmostEqual(result['annualized']['fuel_overrun_nm3'],905200.)
        self.assertTrue(np.isnan(result['power_threshold']))
        self.assertTrue(np.isnan(result['vna_threshold']))

    def test_b_outlier_is_excluded_before_fitting_and_power_is_independent(self):
        d=fixture();d.loc[2,'fuel_specific']=900.
        r=calculate(d);p=r['periods'][0]
        self.assertAlmostEqual(p['k_bприв'],2.)
        self.assertEqual(p['точек регрессии b'],3)
        self.assertAlmostEqual(p['Перерасход, нм³'],197.5)
        self.assertAlmostEqual(p['Недовыработка, МВт·ч'],1.5)
        self.assertEqual((p[POWER_HOURS],p[FUEL_HOURS]),(2.,1.5))
        self.assertTrue(np.isnan(r['row_losses'].fuel_loss_rate.iloc[2]))

    def test_missing_fuel_does_not_zero_power_or_claim_a_known_fuel_total(self):
        d=fixture();d['fuel_specific']=np.nan
        r=calculate(d)
        self.assertAlmostEqual(r['periods'][0]['Недовыработка, МВт·ч'],1.5)
        self.assertTrue(np.isnan(r['periods'][0]['Перерасход, нм³']))
        self.assertEqual(r['annualization_hours'],{'underproduction':2.,'fuel':0.})
        self.assertAlmostEqual(r['annualized']['underproduction_mwh'],6570.)
        self.assertTrue(np.isnan(r['annualized']['fuel_overrun_nm3']))
        self.assertTrue(np.isnan(r['annualized']['total_cost_rub']))

    def test_no_slope_and_partial_period_totals_stay_unknown(self):
        d=fixture(1)
        r=calculate(d)
        self.assertTrue(np.isnan(r['periods'][0]['Недовыработка, МВт·ч']))
        self.assertTrue(np.isnan(r['row_losses'].power_loss_rate.iloc[0]))
        other=fixture();other['period']=2;other['date']+=pd.Timedelta(days=3)
        r=calculate(pd.concat([d,other],ignore_index=True))
        total=r['table'].loc[r['table']['Период'].eq('ИТОГО')].iloc[0]
        self.assertTrue(np.isnan(total['Недовыработка, МВт·ч']))
        self.assertTrue(np.isnan(r['annualized']['underproduction_mwh']))

    def test_valid_improvement_produces_zero_independently(self):
        for power_sign,b_sign in ((1,1),(-1,-1)):
            d=fixture();tau=np.arange(4)*.5
            d['power']=100+power_sign*tau;d['fuel_specific']=300+b_sign*2*tau
            p=calculate(d)['periods'][0]
            self.assertAlmostEqual(p['Недовыработка, МВт·ч'] if power_sign==1 else p['Перерасход, нм³'],0.)
            self.assertGreater(p['Перерасход, нм³'] if power_sign==1 else p['Недовыработка, МВт·ч'],0.)

    def test_gaps_are_reported_without_creating_missing_hours(self):
        d=fixture();d.loc[1:,'date']+=pd.Timedelta(hours=2)
        r=calculate(d)
        self.assertEqual(r['periods'][0]['quality']['missing_half_hours'],4)
        self.assertEqual(r['annualization_hours']['underproduction'],2.)
        self.assertAlmostEqual(r['periods'][0]['Недовыработка, МВт·ч'],1.5)
        for invalid in ('duplicate','irregular','invalid_date','counter'):
            d=fixture()
            if invalid=='duplicate':d.loc[1,'date']=d.loc[0,'date']
            elif invalid=='irregular':d.loc[1,'date']+=pd.Timedelta(minutes=1)
            elif invalid=='invalid_date':d.loc[1,'date']=pd.NaT
            else:d.loc[1,'hours']=d.loc[0,'hours']
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):calculate(d)

    def test_temperature_and_finite_input_checks_precede_regressions(self):
        for value in (-40.,50.,float('inf')):
            d=fixture();d.loc[1,'ambient_temperature']=value
            p=calculate(d)['periods'][0]
            self.assertEqual(p['точек регрессии N'],3)
            self.assertEqual(p[POWER_HOURS],1.5)
            self.assertAlmostEqual(p['k_Nприв'],-1.)
        d=fixture();d['ambient_temperature']=np.nan
        self.assertEqual(calculate(d)['periods'][0][POWER_HOURS],2.)

    def test_vna_hundred_is_in_the_last_distribution_interval(self):
        d=fixture();d['vna']=100.
        p=calculate(d)['periods'][0]
        self.assertEqual(p['Порог ВНА, %'],99.)
        self.assertEqual(p['точек регрессии N'],4)
        self.assertAlmostEqual(p['Недовыработка, МВт·ч'],1.5)

    def test_word_local_thresholds_hours_and_missing_excel_cells(self):
        from reporting import build_report_data
        d=fixture();d['fuel_specific']=np.nan
        result=calculate(d)
        periods=pd.DataFrame([dict(period=1,date_start=d.date.min(),date_end=d.date.max())])
        context=build_report_data(source_data=d,rh_data=d,periods_df=periods,
            boundary_table=None,delta_table=None,vna_results=[],economics_result=result,
            nominal_hours={'power_threshold':999},gas_tariff=2,electricity_tariff=100,electricity_cost=20)
        self.assertEqual(context['economics']['power_threshold_mw'],'90')
        self.assertEqual(context['economics']['annualization_hours'],{'underproduction':'2','fuel':'0'})
        self.assertEqual(context['economics']['total']['fuel_overrun_nm3'],'—')
        self.assertIn('ВНА ≥ 86 %',context['economics']['thresholds_description'])
        frame=pd.DataFrame(dict(E=-1.,F=-1.,G=-1.,H=-1.),index=pd.DatetimeIndex(d.date))
        apply_economic_columns(AssembledData(frame,dict(E='Перерасход',F=None,G='Недовыработка',H=None),0,0,{},[]),result)
        self.assertTrue(frame.E.isna().all())
        self.assertTrue(frame.F.isna().all())
        self.assertAlmostEqual(frame.H.sum(),1.5)


if __name__=='__main__':unittest.main()
