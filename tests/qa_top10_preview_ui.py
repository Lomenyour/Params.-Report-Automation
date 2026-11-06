"""Actual Qt/HTML pair controls and asynchronous preview; synthetic data only."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scr'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from test_compressor_pair_selection import fixture

application = QApplication([])
window = DesktopWindow()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
window.show()
errors = []
window.page.javaScriptConsoleMessage = lambda level, message, line, source: errors.append(message)


def pump(seconds=.05):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        application.processEvents()
        time.sleep(.005)


def js(code):
    results = []
    window.page.runJavaScript(code, lambda value: results.append(value))
    end = time.monotonic()+8
    while not results and time.monotonic() < end:
        pump(.01)
    assert results, code
    return results[0]


def wait_js(code):
    until = time.monotonic()+15
    while time.monotonic() < until:
        if js(code):
            return
        pump(.03)
    raise AssertionError(code)


try:
    until = time.monotonic()+25
    while not window.controller.ready and time.monotonic() < until:
        pump()
    c = window.controller
    assert c.ready, errors
    c.messages.showerror = Mock()
    snapshot = fixture()
    c.last_result = snapshot
    c._show_top10_tables(snapshot.pressure_chart.vna_top10)
    c.chart_tabs.select('top10')
    pump(.15)
    assert js("document.querySelector('#top10-table').textContent==='Таблица'")
    assert js("document.querySelector('#top10-graphs').textContent==='Графики'")
    assert js("document.querySelectorAll('[data-compressor-pair]:checked').length===3")
    js("document.querySelector('[data-compressor-pair=\"2\"][value=\"2\"]').click()")
    wait_js("document.querySelector('[data-compressor-pair=\"2\"][value=\"2\"]').checked")
    assert c.last_result.pressure_chart.compressor_pair_ranks == {2: 2}
    assert c.last_result.data is snapshot.data and c.last_result.sections is snapshot.sections
    js("document.querySelector('#top10-graphs').click()")
    wait_js("document.querySelectorAll('.gtu-compressor-image img').length===3 && [...document.querySelectorAll('.gtu-compressor-image img')].every(x=>x.complete&&x.naturalWidth>0)")
    assert js("document.querySelector('select[data-compressor-pair=\"2\"]').value==='2'")
    first = js("document.querySelector('img[alt$=\"пара №2\"]').src")
    for width, height in ((900, 600), (1200, 800)):
        window.resize(width, height)
        pump(.15)
        assert js("document.documentElement.scrollWidth===innerWidth")
        assert js("[...document.querySelectorAll('.gtu-compressor-select')].every(x=>x.getBoundingClientRect().right<=innerWidth)")
        window.view.grab().save(str(ROOT/f'build_test/top10-graphs-{width}.png'))
    js("const s=document.querySelector('select[data-compressor-pair=\"2\"]'); s.value='3'; s.dispatchEvent(new Event('change',{bubbles:true}));")
    wait_js("document.querySelector('img[alt$=\"пара №3\"]')?.complete")
    assert c.last_result.pressure_chart.compressor_pair_ranks == {2: 3}
    assert js("document.querySelector('img[alt$=\"пара №3\"]').src") != first
    assert js("document.querySelector('select[data-compressor-pair=\"1\"]').value==='1'")
    assert c.last_result.report_data['periods'][1]['vna_top1']['rank'] == '3'
    c.export_running = True
    c.changed()
    wait_js("[...document.querySelectorAll('[data-compressor-pair]')].every(x=>x.disabled)")
    selected = c.last_result
    c.dispatch('compressorPair', json.dumps(dict(period=1, rank=2)))
    assert c.last_result is selected
    c.export_running = False
    c.changed()
    js("document.querySelector('#top10-table').click()")
    wait_js("document.querySelector('[data-compressor-pair=\"2\"][value=\"3\"]')?.checked")
    js("document.querySelector('#top10-table').focus(); document.querySelector('#top10-table').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));")
    wait_js("document.activeElement.id==='top10-graphs'")
    js("document.querySelector('#top10-table').click()")
    wait_js("document.querySelector('[data-compressor-pair=\"2\"][value=\"3\"]')?.checked")
    window.view.grab().save(str(ROOT/'build_test/top10-table-1200.png'))
    c._invalidate_results()
    pump(.1)
    assert js("document.querySelectorAll('.gtu-compressor-image').length===0")
    c.last_result = fixture()
    c._show_top10_tables(c.last_result.pressure_chart.vna_top10)
    pump(.1)
    assert js("document.querySelector('#top10-table').getAttribute('aria-selected')==='true'")
    assert js("[...document.querySelectorAll('[data-compressor-pair]:checked')].every(x=>x.value==='1')")
    assert not errors, errors
    assert not c.messages.showerror.called, c.messages.showerror.call_args
    print('PASS: two subtabs; independent period ranks; shared background previews; table/dropdown sync; 900/1200 layouts; export guard; keyboard focus; invalidation/default reset; no JSON writes')
finally:
    window.close()
    application.processEvents()
