"""The RH k threshold grows only after the plotted-line condition fails."""
from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
import periods
from RH_raschet import main as run_rh, relative_diff, select_rh_pair_steps
from rh_chart import prepare_rh_plots
from rh_display import dirty_above_clean, power_bounds


class RHToleranceStepsTest(unittest.TestCase):
    def pairs(self, *coefficients):
        return pd.DataFrame([dict(period=1,start_id='START_001',end_id=f'END_{i:03d}',
            k_start=200.,k_end=k,b_start=6500.,b_end=b,
            delta_k_pct=relative_diff(200.,k),delta_b_pct=relative_diff(6500.,b),
            power_min=65.,power_max=85.) for i,(k,b) in enumerate(coefficients,1)])

    def choose(self, *coefficients):
        pool = self.pairs(*coefficients)
        before = pool.copy(deep=True)
        chosen,attempts = select_rh_pair_steps(pool)
        pd.testing.assert_frame_equal(pool,before)
        return chosen.iloc[0],attempts

    def test_first_success_at_five_stops_without_widening(self):
        chosen,attempts = self.choose((201.,6500.),(211.,6400.),(213.,6400.))
        self.assertEqual(chosen.end_id,'END_001')
        self.assertTrue(chosen.preferred)
        self.assertEqual(chosen.k_tolerance_percent,5)
        self.assertEqual([a['k_tolerance_percent'] for a in attempts],[5])

    def test_six_is_tried_even_when_five_has_admissible_but_lower_lines(self):
        chosen,attempts = self.choose((199.,6400.),(211.,6400.),(213.,6400.))
        self.assertEqual(chosen.end_id,'END_002')
        self.assertEqual(chosen.k_tolerance_percent,6)
        self.assertEqual(chosen['rank'],2)
        self.assertEqual([a['candidate_count'] for a in attempts],[1,2])
        self.assertEqual([a['preferred'] for a in attempts],[False,True])

    def test_seven_is_tried_after_two_failed_line_checks(self):
        chosen,attempts = self.choose((199.,6400.),(188.,6400.),(213.,6400.))
        self.assertEqual(chosen.end_id,'END_003')
        self.assertEqual(chosen.k_tolerance_percent,7)
        self.assertEqual(chosen['rank'],3)
        self.assertEqual([a['candidate_count'] for a in attempts],[1,2,3])
        self.assertEqual([a['preferred'] for a in attempts],[False,False,True])

    def test_empty_five_pool_can_find_a_pair_at_six(self):
        chosen,attempts = self.choose((211.,6400.))
        self.assertTrue(chosen.preferred)
        self.assertEqual(chosen.k_tolerance_percent,6)
        self.assertEqual([a['candidate_count'] for a in attempts],[0,1])

    def test_b_threshold_stays_five_percent_at_every_level(self):
        chosen,attempts = self.choose((199.,6400.),(211.,6900.),(213.,6900.))
        self.assertEqual(chosen.end_id,'END_001')
        self.assertFalse(chosen.preferred)
        self.assertEqual(chosen.b_tolerance_percent,5)
        self.assertEqual([a['candidate_count'] for a in attempts],[1,1,1])

    def test_six_and_seven_percent_boundaries_are_included(self):
        for k,expected_level in ((212.,6),(214.,7)):
            with self.subTest(k=k):
                chosen,attempts = self.choose((k,6825.))
                self.assertTrue(chosen.preferred)
                self.assertEqual(chosen.k_tolerance_percent,expected_level)
                self.assertAlmostEqual(chosen.delta_k_pct,expected_level)
                self.assertEqual(chosen.delta_b_pct,5)

    def test_above_seven_is_never_admitted_and_old_fallback_is_kept(self):
        chosen,attempts = self.choose((199.,6400.),(214.000002,6400.))
        self.assertEqual(chosen.end_id,'END_001')
        self.assertFalse(chosen.preferred)
        self.assertEqual(chosen.k_tolerance_percent,5)
        self.assertEqual([a['k_tolerance_percent'] for a in attempts],[5,6,7])
        self.assertEqual([a['candidate_count'] for a in attempts],[1,1,1])

    def test_no_admissible_pair_keeps_nearest_with_failure_status(self):
        chosen,attempts = self.choose((215.,6400.))
        self.assertFalse(chosen.preferred)
        self.assertEqual(chosen.candidate_count,0)
        self.assertIn('Нет пары',chosen.status)
        self.assertEqual([a['candidate_count'] for a in attempts],[0,0,0])

    def test_empty_pair_table_stays_empty(self):
        chosen,attempts = select_rh_pair_steps(pd.DataFrame())
        self.assertTrue(chosen.empty)
        self.assertEqual(len(attempts),3)

    def test_real_window_regressions_reach_six_and_seven_and_export_same_pairs(self):
        parts,intervals = [],[]
        for start,k in (('2026-01-01',211.),('2026-01-15',213.)):
            dates = pd.date_range(start,periods=96,freq='30min')
            power = np.tile(np.linspace(65.,85.,48),2)
            fuel = np.r_[200.*power[:48]+6500.,k*power[48:]+6400.]
            parts.append(pd.DataFrame(dict(date=dates,power=power,fuel=fuel,vna=90.,
                                          hours=np.arange(96)*.5)))
            intervals.append((dates[0],dates[-1]))
        source = pd.concat(parts,ignore_index=True)
        original = source.copy(deep=True)
        with patch.object(periods,'PERIOD_OVERRIDES',intervals):
            with contextlib.redirect_stdout(io.StringIO()) as log:
                values,_,results,_ = run_rh(data=source,show_plots=False)
        self.assertEqual([r['k_tolerance_percent'] for r in results],[6.,7.])
        self.assertEqual([len(r['selection_attempts']) for r in results],[2,3])
        self.assertTrue(all(r['preferred'] for r in results))
        plots = prepare_rh_plots(values,results)
        self.assertEqual([p.result for p in plots],results)
        for result in results:
            self.assertTrue(dirty_above_clean(result,power_bounds(values,result)))
            self.assertLessEqual(result['delta_k_pct'],result['k_tolerance_percent'])
            self.assertLessEqual(result['delta_b_pct'],5)
        self.assertIn('Δk ≤ 6%',log.getvalue())
        self.assertIn('Δk ≤ 7%',log.getvalue())
        pd.testing.assert_frame_equal(source,original)


if __name__ == '__main__':
    unittest.main()
