"""Actual Qt/HTML pressure probe and dropdown point counts; synthetic data only."""
from pathlib import Path
import json
import sys
import threading
import time
from unittest.mock import Mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scr'))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from RH_raschet import plot_pressure_drops
from test_compressor_pair_selection import fixture

OUTPUT = ROOT/'build_test/probe_counts_qa_20261112'
OUTPUT.mkdir(parents=True, exist_ok=True)
application = QApplication.instance() or QApplication([])
window = DesktopWindow()
window.resize(1200, 800)
window.show()
controller = window.controller
controller.messages.showerror = Mock()
errors = []
window.page.javaScriptConsoleMessage = lambda level, message, line, source: errors.append(message)


def pump(seconds=.04):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        application.processEvents()
        time.sleep(.005)


def js(code):
    results = []
    window.page.runJavaScript(code, lambda value: results.append(value))
    deadline = time.monotonic()+8
    while not results and time.monotonic() < deadline:
        pump(.01)
    assert results, code
    return results[0]


def wait_js(code):
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        if js(code):
            return
        pump(.02)
    raise AssertionError(code)


def click_record(index):
    probe = controller.views['pressure']['probe']
    fraction = (probe['points'][index][0]-probe['x_min'])/(probe['x_max']-probe['x_min'])
    position = json.loads(js("""(() => {
      const a=document.querySelector('.gtu-pressure-probe'), r=a.getBoundingClientRect();
      const viewport=document.querySelector('.gtu-view-viewport'), v=viewport.getBoundingClientRect();
      const x=r.left+r.width*FRACTION;
      const y=Math.max(r.top,v.top)+Math.min(20,(Math.min(r.bottom,v.top+viewport.clientHeight)-Math.max(r.top,v.top))/2);
      window.probeClickDebug={x,y,hit:document.elementFromPoint(x,y)?.className,
        viewport:v.toJSON(),inert:document.querySelector('main').inert};
      return JSON.stringify({x,y});
    })()""".replace('FRACTION', repr(fraction))))
    point = QPoint(round(position['x']), round(position['y']))
    target = window.view.focusProxy() or window.view
    point = target.mapFrom(window.view, point)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    wait_js(f"document.querySelector('.gtu-probe-readout')?.dataset.index==='{index}'")


try:
    deadline = time.monotonic()+15
    while not controller.ready and time.monotonic() < deadline:
        pump(.02)
    assert controller.ready
    js("window.probeEvents=[]; for (const kind of ['pointerdown','pointerup']) document.addEventListener(kind,e=>{window.probeEvents.push({kind,x:e.clientX,y:e.clientY,target:e.target.className});window.probeEvents=window.probeEvents.slice(-8)},true)")
    values = pd.DataFrame({
        'date': pd.to_datetime(['2026-01-01 00:00', '2026-01-01 00:30',
                               '2026-01-01 01:00', '2026-01-01 04:00', '2026-01-01 04:30']),
        'power': 999., 'power_n': [90., 0., np.nan, 80., 81.],
        'vna': [85., 0., 83., np.nan, 84.], 'fgo': [30., 31., 32., 33., 34.],
        'fto': [80., 81., 82., 83., 84.],
    })
    periods = pd.DataFrame([dict(period=1, date_start=values.date.iloc[0], date_end=values.date.iloc[2]),
                            dict(period=2, date_start=values.date.iloc[3], date_end=values.date.iloc[4])])
    before = values.copy(deep=True)
    figure = plot_pressure_drops(values, periods, show=False)
    red_lines = [line.get_xdata().copy() for line in figure.axes[0].lines]
    controller._show_figure('pressure', figure)
    wait_js("document.querySelector('.gtu-pressure-probe')?.getBoundingClientRect().height>0 && document.querySelector('.gtu-figure')?.complete")
    click_record(1)
    assert 'N: 0 МВт' in js("document.querySelector('.gtu-probe-readout').textContent")
    assert 'ВНА: 0 %' in js("document.querySelector('.gtu-probe-readout').textContent")
    click_record(2)
    assert 'N: нет данных' in js("document.querySelector('.gtu-probe-readout').textContent")
    assert 'ВНА: 83 %' in js("document.querySelector('.gtu-probe-readout').textContent")
    # A true mouse drag, including pointer capture, advances to the next real record.
    rectangle = json.loads(js("JSON.stringify(document.querySelector('.gtu-pressure-probe').getBoundingClientRect().toJSON())"))
    payload = controller.views['pressure']['probe']
    x = lambda i: rectangle['left']+rectangle['width']*(payload['points'][i][0]-payload['x_min'])/(payload['x_max']-payload['x_min'])
    y = round(rectangle['top']+20)
    target = window.view.focusProxy() or window.view
    start = target.mapFrom(window.view, QPoint(round(x(1)), y))
    end = target.mapFrom(window.view, QPoint(round(x(3)), y))
    QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(target, end, delay=30)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    wait_js("document.querySelector('.gtu-probe-readout').dataset.index==='3'")
    assert 'ВНА: нет данных' in js("document.querySelector('.gtu-probe-readout').textContent")
    js("document.querySelector('.gtu-pressure-probe').dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}))")
    wait_js("document.querySelector('.gtu-probe-readout').dataset.index==='0'")
    js("document.querySelector('.gtu-pressure-probe').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
    wait_js("document.querySelector('.gtu-probe-readout').dataset.index==='1'")
    # Zoom around the middle and scroll to the right before selecting an actual date.
    js("""(() => {const v=document.querySelector('.gtu-view-viewport'),r=v.getBoundingClientRect();
      v.dispatchEvent(new WheelEvent('wheel',{deltaY:-120,clientX:r.left+r.width/2,clientY:r.top+20,bubbles:true,cancelable:true}));
      v.scrollLeft=v.scrollWidth;})()""")
    pump(.05)
    click_record(4)
    pump(.2)
    window.view.grab().save(str(OUTPUT/'pressure-1200.png'))
    controller._show_period_choice({'periods_df': periods, 'event': threading.Event()})
    wait_js("document.querySelector('#dialog-layer.periods textarea')!==null")
    period_text = js("document.querySelector('#dialog-layer.periods textarea').value")
    js("document.querySelector('.gtu-pressure-probe').dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}))")
    assert js("document.querySelector('#dialog-layer.periods textarea').value") == period_text
    assert 'overrides' not in controller.period_request
    controller.resolve_dialog({'action': 'auto'})
    # Dropdown counts are present for unrendered pairs, including zero selections.
    snapshot = fixture()
    snapshot.pressure_chart.vna_top10[0]['count'] = 999
    v = snapshot.pressure_chart.degradation_values
    v.loc[v.period.eq(1) & v.vna.ge(86.6), 'pi_k'] = np.nan
    controller.last_result = snapshot
    controller._show_top10_tables(snapshot.pressure_chart.vna_top10)
    counts = controller.views['top10']['tables'][0]['pairs']
    assert [p['points'] for p in counts] == [2, 2, 0]
    assert all('точек: '+str(p['points']) in p['label'] for p in counts)
    js("document.querySelector('[data-tab=top10]').click()")
    wait_js("document.querySelector('#top10-graphs')!==null")
    js("document.querySelector('#top10-graphs').click()")
    wait_js("document.querySelector('[data-compressor-pair=\"1\"] option[value=\"3\"]')?.textContent.includes('точек: 0')")
    wait_js("document.querySelectorAll('.gtu-compressor-image').length===3")
    for table in controller.views['top10']['tables']:
        assert table['preview']['points'] == next(p['points'] for p in table['pairs'] if p['rank']==table['selected_rank'])
    js("const s=document.querySelector('[data-compressor-pair=\"1\"]');s.value='3';s.dispatchEvent(new Event('change',{bubbles:true}))")
    wait_js("document.querySelector('.gtu-compressor-message')?.textContent.includes('нет измерений')")
    pump(.2)
    window.view.grab().save(str(OUTPUT/'counts-1200.png'))
    js("document.querySelector('[data-tab=pressure]').click()")
    wait_js("document.querySelector('.gtu-probe-readout')?.dataset.index==='0'")
    window.resize(900, 600)
    pump(.15)
    js("document.querySelector('.gtu-journal').open=false")
    pump(.05)
    js("document.querySelector('.gtu-view-viewport').scrollLeft=0")
    click_record(1)
    pump(.2)
    window.view.grab().save(str(OUTPUT/'pressure-900.png'))
    for actual, expected in zip(figure.axes[0].lines, red_lines):
        np.testing.assert_array_equal(actual.get_xdata(), expected)
    pd.testing.assert_frame_equal(values, before)
    assert not errors, errors
    assert not controller.messages.showerror.called, controller.messages.showerror.call_args
    controller._clear_charts()
    controller._show_figure('pressure', figure)
    wait_js("document.querySelector('.gtu-pressure-probe')!==null")
    assert js("document.querySelector('.gtu-probe-readout').dataset.index") != '1'
    result = dict(real_mouse_drag=True, zoom_scroll_resize=True, zero_and_missing=True,
        period_dates_unchanged=True, source_unchanged=True, tab_position_preserved=True,
        reset=True, unopened_pair_counts=[2, 2, 0], preview_counts_match=True, js_errors=errors)
    (OUTPUT/'ui.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
except Exception:
    window.view.grab().save(str(OUTPUT/'failure.png'))
    print(js("JSON.stringify({probe:document.querySelector('.gtu-pressure-probe')?.getBoundingClientRect().toJSON(),readout:document.querySelector('.gtu-probe-readout')?.textContent,dialog:document.querySelector('.gtu-dialog')?.className,click:window.probeClickDebug,events:window.probeEvents})"))
    raise
finally:
    window.close()
    application.processEvents()
