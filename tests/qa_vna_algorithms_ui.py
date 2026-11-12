"""Real Qt/WebChannel validation of both algorithms and model-style menus."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scr'),str(ROOT/'tests')]
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from test_compressor_pair_selection import fixture

OUTPUT=ROOT/'build_test/vna_algorithm2_qa_20261112'
OUTPUT.mkdir(parents=True,exist_ok=True)
app=QApplication([])
window=DesktopWindow()
window.show()
errors=[]
window.page.javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)


def pump(seconds=.1):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        app.processEvents()
        time.sleep(.005)


def js(code):
    results=[]
    expression='(()=>{'+code+';return null;})()' if code.lstrip().startswith('const ') else code
    window.page.runJavaScript('JSON.stringify('+expression+')',
        lambda value:results.append(json.loads(value) if value else None))
    until=time.monotonic()+8
    while not results and time.monotonic()<until:
        pump(.01)
    assert results,code
    return results[0]


def wait(code):
    until=time.monotonic()+20
    while time.monotonic()<until:
        if js(code):
            return
        pump(.03)
    raise AssertionError((code,js('({width:innerWidth,height:innerHeight,ratio:devicePixelRatio})'),
                          (window.width(),window.height(),window.view.width(),window.view.height()),errors[:3]))


def click(selector):
    point=js(f'''(()=>{{const node=document.querySelector({json.dumps(selector)});node.scrollIntoView({{block:'nearest'}});
        const r=node.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()''')
    # Deliver actual native input, not a JavaScript .click() shortcut.
    target=window.view.focusProxy() or window.view
    mapped=target.mapFrom(window.view,QPoint(round(point[0]),round(point[1])))
    QTest.mouseClick(target,Qt.MouseButton.LeftButton,pos=mapped)
    pump(.1)


report={}
try:
    until=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<until:
        pump()
    c=window.controller
    assert c.ready,errors
    c.messages.showerror=Mock()
    window.resize(1200,800)
    wait('innerWidth===1200 && innerHeight===800')
    click('#station-choice')
    wait("document.querySelector('.gtu-choice-popup')!==null")
    assert js("getComputedStyle(document.querySelector('.gtu-choice-popup')).borderRadius==='13px'")
    assert js("document.querySelectorAll('.gtu-choice-popup [aria-selected=true]').length===1")
    assert js("document.querySelectorAll('.gtu-choice-popup [role=option]').length>20")
    js("const items=document.querySelectorAll('.gtu-choice-popup [role=option]');items[2].dispatchEvent(new PointerEvent('pointermove',{bubbles:true}));")
    assert js("document.querySelector('.gtu-choice-popup [aria-selected=true]')!==document.querySelector('.gtu-choice-popup [data-active=true]')")
    assert js("getComputedStyle(document.querySelector('.gtu-choice-popup [aria-selected=true]'),'::after').content.includes('✓')")
    window.view.grab().save(str(OUTPUT/'station-menu-1200.png'))
    target=window.view.focusProxy() or window.view
    QTest.keyClick(target,Qt.Key.Key_Escape)
    wait("document.querySelector('.gtu-choice-popup')===null")
    # Pick a real station through keyboard; this only selects the catalogue.
    click('#station-choice')
    QTest.keyClick(target,Qt.Key.Key_End)
    QTest.keyClick(target,Qt.Key.Key_Return)
    wait("document.querySelector('#station').selectedIndex>0")
    pump(.2)
    assert c.station_var.get()==js("document.querySelector('#station').value")
    click('#unit-choice')
    wait("document.querySelector('.gtu-choice-popup')!==null")
    window.view.grab().save(str(OUTPUT/'unit-menu-1200.png'))
    QTest.keyClick(target,Qt.Key.Key_Escape)
    c.last_result=fixture().with_compressor_pair(2,3)
    original=c.last_result
    c._show_top10_tables(c.last_result.pressure_chart.vna_top10)
    c.chart_tabs.select('top10')
    wait("document.querySelector('[data-compressor-algorithm=\"1\"]')?.getAttribute('aria-pressed')==='true'")
    click('#top10-graphs')
    wait("document.querySelectorAll('.gtu-compressor-image img').length===3 && [...document.querySelectorAll('.gtu-compressor-image img')].every(x=>x.complete && x.naturalWidth>0)")
    layouts=[]
    for width,height in ((900,600),(1200,800),(1600,1000)):
        window.resize(width,height)
        wait(f'innerWidth==={width} && innerHeight==={height}')
        pump(.35)
        dimensions=js('''(()=>{const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {width:r.width,height:r.height,x:r.x,y:r.y};};
            return {viewport:rect('.gtu-view-viewport'),image:rect('.gtu-compressor-image img'),overflow:document.documentElement.scrollWidth>innerWidth,
                rounded:getComputedStyle(document.querySelector('.gtu-choice input')).borderRadius,font:getComputedStyle(document.querySelector('.gtu-choice input')).fontFamily};})()''')
        assert dimensions['viewport']['height']>75,dimensions
        assert 0<dimensions['image']['height']<=360.5,dimensions
        assert not dimensions['overflow'],dimensions
        assert js("[...document.querySelectorAll('select.gtu-field')].every(x=>x.hidden)")
        layouts.append(dict(width=width,height=height,**dimensions))
        window.view.grab().save(str(OUTPUT/f'top10-fit-{width}.png'))
    report['layouts']=layouts
    click('[data-compressor-choice="2"]')
    wait("document.querySelector('.gtu-choice-popup')!==null")
    assert js("[...document.querySelectorAll('.gtu-choice-popup [role=option]')].every(x=>x.textContent.includes('точек: 2'))")
    window.view.grab().save(str(OUTPUT/'pair-menu-1600.png'))
    QTest.keyClick(target,Qt.Key.Key_Escape)
    click('[data-compressor-algorithm="2"]')
    wait("document.querySelector('[data-compressor-algorithm=\"2\"]')?.getAttribute('aria-pressed')==='true' && !document.querySelector('[data-compressor-algorithm=\"1\"]').disabled")
    wait("document.querySelectorAll('.gtu-compressor-image img').length===3 && [...document.querySelectorAll('.gtu-compressor-image img')].every(x=>x.complete && x.naturalWidth>0)")
    assert c.last_result.pressure_chart.compressor_algorithm==2
    assert all(len(table)==1 and table.iloc[0].plot_points==2 for table in c.last_result.pressure_chart.vna_top10)
    assert c.last_result.data is original.data
    assert c.last_result.report_data['economics']==original.report_data['economics']
    window.view.grab().save(str(OUTPUT/'algorithm2-1600.png'))
    click('[data-compressor-algorithm="1"]')
    wait("document.querySelector('[data-compressor-choice=\"2\"]')?.value.includes('Пара №3')")
    assert c.last_result.pressure_chart.compressor_pair_ranks=={2:3}
    c.export_running=True
    c.changed()
    wait("[...document.querySelectorAll('[data-compressor-algorithm]')].every(x=>x.disabled)")
    assert js("[...document.querySelectorAll('[data-compressor-choice]')].every(x=>x.disabled)")
    c.export_running=False
    c.changed()
    assert not errors,errors
    c.messages.showerror.assert_not_called()
    report.update(algorithms=True,cached_return=True,menus_keyboard_hover_check=True,export_guard=True,console_errors=errors)
    (OUTPUT/'ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: native menu input, checked/hover states, keyboard, 900/1200/1600 layouts, 360px fit, algorithm 2, cached return and export guards')
finally:
    window.close()
    app.processEvents()
