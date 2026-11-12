"""Pair selection changes only compressor presentation, never analytical results."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scr'))
from calculation_snapshot import CalculationSnapshot
from compressor_degradation_chart import prepare_compressor_plots, compressor_pair_point_counts
from compressor_preview import compressor_preview_figure
from desktop_controller import DesktopController
from pressure_chart import PressureChartData
from reporting import _vna_top_context
from result_export import DataSheetValues, save_result_workbook


def fixture():
    records, tables, periods = [], [], []
    for number in (1, 2, 3):
        start = pd.Timestamp(2026, number, 1)
        pairs = []
        for rank, (left, right) in enumerate(((0, 5), (1, 4), (2, 3)), 1):
            vna, temperature, pressure = 86 + rank*.2 + .01, 10.+rank, 990.+rank
            eta = 84.+rank*.1
            for offset, day in enumerate((left, right)):
                records.append(dict(period=number, date=start+pd.Timedelta(days=day),
                    vna=vna, t=temperature, p=pressure, tkk=370., eta_compressor=eta-offset*.02,
                    pi_k=14.+rank*.1-offset*.01, excel_row=len(records)+2,
                    vlo=200., power_n=90.))
            pairs.append(dict(rank=rank, vna_interval=f'{86+rank*.2:.1f}-{86+rank*.2+.1:.1f}',
                count=2, share_percent=100/3, date_1=start+pd.Timedelta(days=left),
                date_2=start+pd.Timedelta(days=right), t_1=temperature, t_2=temperature,
                p_1=pressure, p_2=pressure, vna_1=vna, vna_2=vna, tkk_1=370., tkk_2=370.,
                eta_1=eta, eta_2=eta-.02, pi_k_1=14.+rank*.1, pi_k_2=14.+rank*.1-.01,
                delta_days=float(right-left), delta_eta=.02, delta_t=0., delta_p=0.))
        table = pd.DataFrame(pairs)
        table.attrs['period_number'] = number
        tables.append(table)
        periods.append(dict(period=number, date_start=start, date_end=start+pd.Timedelta(days=5)))
    values = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
    periods = pd.DataFrame(periods)
    raw = pd.DataFrame([['Дата', 'ВЛО, Па', 'N, МВт']] +
                       [[row.date, row.vlo, row.power_n] for row in values.itertuples()])
    chart = PressureChartData(values, periods, None, degradation_values=values, vna_top10=tables)
    context = dict(periods=[dict(number=n, vna_top1=_vna_top_context(table),
                                deltas=dict(n_priv='1', b_priv='2', eta_gtu_pp='3'))
                           for n, table in enumerate(tables, 1)], economics=dict(total=123))
    return CalculationSnapshot(DataSheetValues(raw, 0),
        [('Расчётные итоги', pd.DataFrame({'ΔN': [1.], 'Δb': [2.]}))] +
        [(f'ТОП-10 {n}', table) for n, table in enumerate(tables, 1)], chart, context, (), 'qa')


class PairSelectionTest(unittest.TestCase):
    def test_algorithm_switch_remembers_choices_and_changes_only_compressor_exports(self):
        original=fixture().with_compressor_pair(2,3)
        tables=[table.copy(deep=True) for table in original.pressure_chart.vna_top10]
        for table in tables:
            table['plot_points']=2
        second=original.with_compressor_algorithm(2,tables).with_compressor_pair(1,2)
        self.assertEqual(second.pressure_chart.compressor_algorithm,2)
        self.assertEqual(second.pressure_chart.compressor_pair_ranks,{1:2})
        self.assertEqual(second.report_data['periods'][0]['vna_top1']['rank'],'2')
        self.assertEqual(second.report_data['periods'][1]['vna_top1']['rank'],'1')
        self.assertTrue(all('Алгоритм 2' in title for title,_ in second.sections[1:]))
        self.assertTrue(all('plot_points' in table for _,table in second.sections[1:]))
        self.assertIs(second.sections[0],original.sections[0])
        for name in ('data','book_profile','input_files'):
            self.assertIs(getattr(second,name),getattr(original,name))
        for name in ('values','periods','degradation_values','rh_values','rh_results'):
            self.assertIs(getattr(second.pressure_chart,name),getattr(original.pressure_chart,name))
        self.assertEqual(second.report_data['economics'],original.report_data['economics'])
        restored=second.with_compressor_algorithm(1)
        self.assertIs(restored.pressure_chart.vna_top10,original.pressure_chart.vna_top10)
        self.assertEqual(restored.pressure_chart.compressor_pair_ranks,{2:3})
        self.assertEqual(restored.report_data['periods'],original.report_data['periods'])
        self.assertEqual([title for title,_ in restored.sections],[title for title,_ in original.sections])
        again=restored.with_compressor_algorithm(2)
        self.assertEqual(again.pressure_chart.compressor_pair_ranks,{1:2})
        self.assertEqual(again.report_data['periods'],second.report_data['periods'])
        self.assertNotIn('compressor_algorithm',original.report_data)

    def test_empty_second_algorithm_has_no_word_or_chart_fallback(self):
        from vna_density import calculate_density_top10
        original=fixture()
        values=original.pressure_chart.degradation_values.copy()
        values['t']=np.arange(len(values))*10.
        tables=calculate_density_top10(values,original.pressure_chart.periods)
        second=original.with_compressor_algorithm(2,tables)
        self.assertTrue(all(table.empty for table in tables))
        self.assertFalse(prepare_compressor_plots(second.pressure_chart.degradation_values,
            second.pressure_chart.periods,second.pressure_chart.vna_top10))
        self.assertTrue(all(period['vna_top1']['rank']=='—' for period in second.report_data['periods']))
        self.assertTrue(all('2/3' in table.iloc[0,0] for _,table in second.sections[1:]))
        self.assertEqual(second.with_compressor_algorithm(1).report_data['periods'],original.report_data['periods'])

    def test_second_algorithm_excel_charts_match_word_and_actual_point_counts(self):
        from vna_density import calculate_density_top10
        from tempfile import TemporaryDirectory
        original=fixture()
        chart=original.pressure_chart
        tables=calculate_density_top10(chart.degradation_values,chart.periods)
        snapshot=original.with_compressor_algorithm(2,tables)
        with TemporaryDirectory() as directory:
            path=Path(directory)/'second.xlsx'
            save_result_workbook(snapshot.data,snapshot.sections,path,pressure_chart=snapshot.pressure_chart)
            book=load_workbook(path)
            self.addCleanup(book.close)
            charts=book['Графики']._charts[-3:]
            plots=prepare_compressor_plots(chart.degradation_values,chart.periods,tables)
            for index,(table,plot,graph) in enumerate(zip(tables,plots,charts)):
                self.assertEqual(table.iloc[0].plot_points,len(plot.points))
                actual=[point.v for point in graph.series[0].yVal.numRef.numCache.pt]
                np.testing.assert_allclose(actual,plot.points.eta)
                self.assertEqual(snapshot.report_data['periods'][index]['vna_top1']['point_1']['date'],
                                 table.iloc[0].date_1.strftime('%d-%m-%Y %H:%M'))

    def test_invalid_algorithm_and_uncalculated_second_variant(self):
        original=fixture()
        for value in (True,1.,'2',None,0,3):
            with self.subTest(value=value),self.assertRaises(ValueError):
                original.with_compressor_algorithm(value)
        with self.assertRaisesRegex(ValueError,'ещё не рассчитан'):
            original.with_compressor_algorithm(2)
        self.assertIs(original.with_compressor_algorithm(1),original)

    def test_candidate_counts_are_filtered_plot_points_not_window_counts(self):
        chart = fixture().pressure_chart
        for table in chart.vna_top10:
            table['count'] = 999
        values = chart.degradation_values
        rows = {rank: values.index[values.period.eq(1) &
                    values.vna.ge(86+rank*.2) & values.vna.lt(86+rank*.2+.1)]
                for rank in (1, 2, 3)}
        values.loc[rows[1][0], 'eta_compressor'] = np.nan
        values.loc[rows[2][0], 'pi_k'] = np.inf
        values.loc[rows[3], 'pi_k'] = np.nan
        before = values.copy(deep=True)
        tables = [table.copy(deep=True) for table in chart.vna_top10]
        counts = compressor_pair_point_counts(values, chart.periods, chart.vna_top10)
        self.assertEqual(counts, {(number, rank):
            ({1: 1, 2: 1, 3: 0}[rank] if number == 1 else 2)
            for number in (1, 2, 3) for rank in (1, 2, 3)})
        pd.testing.assert_frame_equal(values, before)
        for actual, expected in zip(chart.vna_top10, tables):
            pd.testing.assert_frame_equal(actual, expected)

    def test_only_selected_period_changes_and_defaults_are_identical(self):
        original = fixture()
        top10 = [table.copy(deep=True) for table in original.pressure_chart.vna_top10]
        before_context = copy.deepcopy(original.report_data)
        changed = original.with_compressor_pair(2, 3)
        for name in ('data', 'sections', 'book_profile'):
            self.assertIs(getattr(changed, name), getattr(original, name))
        self.assertIs(changed.pressure_chart.values, original.pressure_chart.values)
        self.assertIs(changed.pressure_chart.vna_top10, original.pressure_chart.vna_top10)
        self.assertIsNone(original.pressure_chart.compressor_pair_ranks)
        self.assertEqual(changed.pressure_chart.compressor_pair_ranks, {2: 3})
        self.assertEqual(changed.report_data['periods'][1]['vna_top1']['rank'], '3')
        self.assertEqual(changed.report_data['periods'][0], original.report_data['periods'][0])
        self.assertEqual(changed.report_data['periods'][2], original.report_data['periods'][2])
        self.assertEqual(changed.report_data['periods'][1]['deltas'], original.report_data['periods'][1]['deltas'])
        self.assertEqual(changed.report_data['economics'], original.report_data['economics'])
        self.assertEqual(original.report_data, before_context)
        self.assertEqual(changed.with_compressor_pair(2, 1).report_data, original.report_data)
        plots = lambda s: prepare_compressor_plots(s.pressure_chart.degradation_values,
            s.pressure_chart.periods, s.pressure_chart.vna_top10, s.pressure_chart.compressor_pair_ranks)
        old, new = plots(original), plots(changed)
        self.assertEqual([p.pair_rank for p in new], [1, 3, 1])
        self.assertEqual([len(p.points) for p in new], [2, 2, 2])
        for index in (0, 2):
            pd.testing.assert_frame_equal(new[index].points, old[index].points)
        self.assertNotEqual(new[1].points.excel_row.tolist(), old[1].points.excel_row.tolist())
        for actual, expected in zip(original.pressure_chart.vna_top10, top10):
            pd.testing.assert_frame_equal(actual, expected)
        missing = original.pressure_chart.degradation_values.copy(deep=True)
        missing.loc[(missing.period == 2) & (missing.vna > 86.6), 'eta_compressor'] = np.nan
        empty_pair = prepare_compressor_plots(missing, original.pressure_chart.periods,
            original.pressure_chart.vna_top10, {2: 3})
        self.assertEqual([plot.period for plot in empty_pair], [1, 3])  # No TOP-1 fallback.

    def test_invalid_or_ambiguous_choices_raise_without_mutating_snapshot(self):
        original = fixture()
        for period, rank in ((0, 1), (4, 1), (1, 0), (1, 4), (True, 2),
                             (1, True), ('1', 2), (1, 2.5), (1, None)):
            with self.subTest(period=period, rank=rank), self.assertRaises(ValueError):
                original.with_compressor_pair(period, rank)
        original.pressure_chart.vna_top10[0].loc[1, 'rank'] = 1
        with self.assertRaisesRegex(ValueError, 'однозначной'):
            original.with_compressor_pair(1, 1)
        self.assertIsNone(original.pressure_chart.compressor_pair_ranks)

        chosen = fixture().with_compressor_pair(1, 2)
        # True/1.0 must not alias an existing integer dictionary key.
        for invalid in (True, 1.0):
            with self.subTest(period=invalid), self.assertRaises(ValueError):
                chosen.with_compressor_pair(invalid, 3)

    def test_preview_uses_excel_points_scales_and_handles_single_or_flat_series(self):
        original = fixture().with_compressor_pair(1, 2)
        chart = original.pressure_chart
        plot = prepare_compressor_plots(chart.degradation_values, chart.periods,
                                        chart.vna_top10, chart.compressor_pair_ranks)[0]
        for points in (plot.points, plot.points.iloc[:1], plot.points.assign(eta=84., pi_k=14.)):
            selected = copy.copy(plot)
            selected.points = points
            figure = compressor_preview_figure(selected)
            try:
                for axis, key in zip(figure.axes, ('eta', 'pi_k')):
                    np.testing.assert_array_equal(axis.lines[0].get_ydata(), points[key])
                    np.testing.assert_array_equal(axis.lines[0].get_xdata(), mdates.date2num(points.date.to_numpy()))
                    self.assertLessEqual(axis.get_ylim()[0], points[key].min())
                    self.assertGreaterEqual(axis.get_ylim()[1], points[key].max())
            finally:
                figure.clear()

    def test_excel_uses_selected_pair_without_reordering_top10(self):
        snapshot = fixture().with_compressor_pair(2, 3)
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory)/'result.xlsx'
            save_result_workbook(snapshot.data, snapshot.sections, path, pressure_chart=snapshot.pressure_chart)
            book = load_workbook(path)
            self.addCleanup(book.close)
            charts = book['Графики']._charts
            # Pressure chart, overall GTU chart, then compressor periods.
            compressor = charts[-3:]
            self.assertAlmostEqual(compressor[1].series[0].yVal.numRef.numCache.pt[0].v, 84.3)
            self.assertAlmostEqual(compressor[0].series[0].yVal.numRef.numCache.pt[0].v, 84.1)
            texts = [cell.value for row in book['Графики'] for cell in row if isinstance(cell.value, str)]
            self.assertTrue(any('Период 2.' in text and 'TOP-3' in text for text in texts))
            self.assertEqual(snapshot.pressure_chart.vna_top10[1]['rank'].tolist(), [1, 2, 3])


_application = None


class DesktopPairSelectionTest(unittest.TestCase):
    def setUp(self):
        global _application
        _application = QApplication.instance() or QApplication([])
        self.window = QWidget()
        self.controller = DesktopController(self.window)
        self.controller.messages.showerror = Mock()
        self.controller.last_result = fixture()
        self.controller._show_top10_tables(self.controller.last_result.pressure_chart.vna_top10)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.closed = True
        self.controller._clear_charts()
        self.window.close()
        self.window.deleteLater()
        _application.processEvents()

    def test_selection_and_export_guards_do_not_run_calculations(self):
        c = self.controller
        self.assertEqual(c.views['top10']['mode'], 'table')
        with patch('desktop_controller.threading.Thread') as thread:
            c.dispatch('compressorPair', json.dumps(dict(period=2, rank=3)))
            thread.assert_not_called()  # Preview is lazy, table selection needs no worker.
        snapshot = c.last_result
        self.assertEqual(snapshot.pressure_chart.compressor_pair_ranks, {2: 3})
        self.assertEqual([x['selected_rank'] for x in c.views['top10']['tables']], [1, 3, 1])
        for flag in ('export_running', 'calculation_running'):
            setattr(c, flag, True)
            c.dispatch('compressorPair', json.dumps(dict(period=1, rank=2)))
            self.assertIs(c.last_result, snapshot)
            setattr(c, flag, False)
        c.dispatch('compressorPair', json.dumps(dict(period=1, rank=99)))
        self.assertIs(c.last_result, snapshot)
        c.messages.showerror.assert_called_once()

    def test_real_second_algorithm_background_and_cached_return(self):
        c=self.controller
        before=c.last_result.with_compressor_pair(2,3)
        c.last_result=before
        c.dispatch('compressorAlgorithm',json.dumps(dict(algorithm=2)))
        self.assertTrue(c.calculation_running)
        deadline=time.monotonic()+10
        while c.calculation_running and time.monotonic()<deadline:
            _application.processEvents()
            time.sleep(.005)
        self.assertFalse(c.calculation_running)
        self.assertEqual(c.views['top10']['algorithm'],2)
        self.assertTrue(all(len(table)==1 for table in c.last_result.pressure_chart.vna_top10))
        self.assertTrue(all(table.iloc[0].plot_points==2 for table in c.last_result.pressure_chart.vna_top10))
        self.assertIsNone(c._compressor_algorithm_job)
        with patch('desktop_controller.threading.Thread') as thread:
            c.select_compressor_algorithm(1)
            self.assertEqual(c.last_result.pressure_chart.compressor_pair_ranks,{2:3})
            c.select_compressor_algorithm(2)
            thread.assert_not_called()
        c.messages.showerror.assert_not_called()

    def test_algorithm_guards_and_stale_completion_do_not_replace_new_results(self):
        c=self.controller
        before=c.last_result
        for flag in ('calculation_running','export_running'):
            setattr(c,flag,True)
            c.select_compressor_algorithm(2)
            self.assertIs(c.last_result,before)
            setattr(c,flag,False)
        with patch('desktop_controller.threading.Thread'):
            c.select_compressor_algorithm(2)
            old_job=c._compressor_algorithm_job
            self.assertTrue(c.calculation_running)
            c._invalidate_results()
            self.assertFalse(c.calculation_running)
            c.last_result=fixture()
            new=c.last_result
            c.select_compressor_algorithm(2)
            c._finish_compressor_algorithm(dict(snapshot=before,job=old_job,tables=[],seconds=0))
            self.assertIs(c.last_result,new)
            self.assertTrue(c.calculation_running)
            c._finish_compressor_algorithm(dict(snapshot=new,job=c._compressor_algorithm_job,error='QA failure',seconds=0))
            self.assertFalse(c.calculation_running)
            self.assertIs(c.last_result,new)
            self.assertEqual(c.last_result.pressure_chart.compressor_algorithm,1)
            c.messages.showerror.assert_called_once()

    def test_all_dropdown_counts_are_ready_before_preview_and_cached(self):
        c = self.controller
        pairs = [pair for table in c.views['top10']['tables'] for pair in table['pairs']]
        self.assertEqual([pair['points'] for pair in pairs], [2]*9)
        self.assertTrue(all('точек: 2' in pair['label'] for pair in pairs))
        self.assertFalse(c._compressor_preview_cache)
        with patch('desktop_controller.compressor_pair_point_counts') as recount:
            c.select_compressor_pair(2, 3)
            recount.assert_not_called()
        c._invalidate_results()
        self.assertFalse(c._compressor_point_counts)
        self.assertIsNone(c._compressor_point_counts_key)
        c.last_result = fixture()
        c._show_top10_tables(c.last_result.pressure_chart.vna_top10)
        self.assertEqual(len(c._compressor_point_counts), 9)

    def test_stale_preview_is_discarded_and_invalidation_resets_selection(self):
        c = self.controller
        before = c.last_result
        c.select_compressor_pair(2, 2)
        c._finish_compressor_previews(dict(snapshot=before, images={(2, 1): dict(src='stale')}))
        self.assertFalse(c._compressor_preview_cache)
        c._invalidate_results()
        self.assertIsNone(c.last_result)
        c._finish_compressor_previews(dict(snapshot=before, images={(2, 1): dict(src='stale')}))
        self.assertNotIn('top10', c.views)
        c.last_result = fixture()
        c._show_top10_tables(c.last_result.pressure_chart.vna_top10)
        self.assertEqual(c.views['top10']['mode'], 'table')
        self.assertEqual([x['selected_rank'] for x in c.views['top10']['tables']], [1, 1, 1])

    def test_real_background_preview_finishes_without_touching_snapshot(self):
        c = self.controller
        snapshot = c.last_result
        c.dispatch('top10Mode', json.dumps(dict(mode='graphs')))
        deadline = time.monotonic()+12
        while c._compressor_preview_busy and time.monotonic() < deadline:
            _application.processEvents()
            time.sleep(.01)
        self.assertFalse(c._compressor_preview_busy)
        self.assertIs(c.last_result, snapshot)
        self.assertEqual(len(c._compressor_preview_cache), 3)
        self.assertTrue(all(x['preview'].get('src', '').startswith('data:image/png;base64,')
                            for x in c.views['top10']['tables']))


if __name__ == '__main__':
    unittest.main()
