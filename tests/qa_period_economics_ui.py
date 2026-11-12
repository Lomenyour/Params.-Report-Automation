"""Qt/HTML economy table exposes local thresholds, hours and unavailable states."""
from pathlib import Path
import json
import sys
import time

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scr'),str(ROOT/'tests')]
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from test_period_economics import fixture,calculate

app=QApplication([])
window=DesktopWindow();window.show()
errors=[]
window.page.javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)


def pump(seconds=.05):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.005)


def js(code):
    result=[];window.page.runJavaScript(code,lambda value:result.append(value))
    until=time.monotonic()+8
    while not result and time.monotonic()<until:pump()
    assert result,code
    return result[0]


def wait(code):
    until=time.monotonic()+20
    while time.monotonic()<until:
        if js(code):return
        pump()
    raise AssertionError(code)


try:
    until=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<until:pump()
    assert window.controller.ready,errors
    data=fixture();data['fuel_specific']=float('nan')
    result=calculate(data)
    c=window.controller;c._show_table('economics',result['table']);c.chart_tabs.select('economics')
    wait("document.querySelector('.gtu-data-table')!==null")
    assert js("document.querySelector('.gtu-data-table').textContent.includes('Порог Nприв, МВт')")
    assert js("document.querySelector('.gtu-data-table').textContent.includes('Учтено для перерасхода, ч')")
    assert js("document.querySelector('.gtu-data-table').textContent.includes('газ: нет данных')")
    assert not js("document.querySelector('.gtu-data-table').textContent.includes('NaN')")
    assert not js("document.querySelector('.gtu-data-table').textContent.includes('nan')")
    for width,height in ((900,600),(1200,800)):
        window.resize(width,height);pump(.3)
        assert js('document.documentElement.scrollWidth===innerWidth')
        assert js("document.querySelector('.gtu-view-viewport').scrollWidth>document.querySelector('.gtu-view-viewport').clientWidth")
        js("document.querySelector('.gtu-view-viewport').scrollLeft=10000")
        pump(.1)
        window.view.grab().save(str(ROOT/f'build_test/period_economics_qa_20261112/economics-{width}.png'))
    assert not errors,errors
    print('PASS: local thresholds, separate eligible hours, unavailable result labels, 900/1200 horizontal table scrolling; no JS errors')
finally:
    window.close();app.processEvents()
