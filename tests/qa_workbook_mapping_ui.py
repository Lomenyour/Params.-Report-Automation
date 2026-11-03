"""Run separately; actual Qt/HTML controls with synthetic workbook, no settings writes."""
from pathlib import Path
import json
import sys
import tempfile
import time
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scr'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from desktop_controller import BookMappingDialog
from workbook_profile import read_layout,suggestions
from test_workbook_profiles import fixture

application=QApplication([]);window=DesktopWindow()
window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);window.show()
errors=[];window.page.javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)

def pump(seconds=.1):
    until=time.monotonic()+seconds
    while time.monotonic()<until:application.processEvents();time.sleep(.005)

def js(code):
    result=[];window.page.runJavaScript(code,lambda value:result.append(value))
    end=time.monotonic()+8
    while not result and time.monotonic()<end:pump(.01)
    assert result,code
    return result[0]

def choose(label,value):
    assert js(f'''(()=>{{const input=[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==={json.dumps(label)});
    input.scrollIntoView({{block:'center'}});input.closest('.gtu-choice').querySelector('button').click();
    const popup=document.querySelector('.gtu-choice-popup'),r=popup.getBoundingClientRect();
    if(r.top<0||r.bottom>innerHeight+1)return false;
    const option=[...popup.querySelectorAll('[role=option]')].find(x=>x.textContent==={json.dumps(value)});
    if(!option)return false;option.dispatchEvent(new PointerEvent('pointerdown',{{bubbles:true,cancelable:true}}));return true;}})()''')
    pump(.05)

try:
    until=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<until:pump(.05)
    assert window.controller.ready,errors
    c=window.controller;c.messages.showerror=Mock()
    with tempfile.TemporaryDirectory() as temporary,patch('workbook_profile.profile_path',return_value=Path(temporary)/'profiles.json'):
        path=Path(temporary)/'book.xlsx';fixture(path)
        layout=read_layout(path);rows=suggestions(layout,'station','1')
        for size in ((900,600),(1200,800)):
            window.resize(*size);pump(.1)
            dialog=BookMappingDialog(c,layout,rows,'station','1');c.dialog=dialog
            c.dialog_changed.emit(json.dumps(dialog.payload,ensure_ascii=False));pump(.15)
            assert js("document.querySelector('.gtu-dialog [aria-label=\"Параметр C\"]').value==='Дата и время'")
            choose('Параметр A','Вспомогательная колонка')
            choose('Параметр A','Температура перед компрессором')
            choose('Единицы A','°C')
            choose('Тип N','Измеренный');choose('Тип N','Расчётный')
            js("document.querySelector('.gtu-dialog-body').scrollTop=0");pump(.05)
            window.view.grab().save(str(ROOT/f'build_test/workbook-mapping-{size[0]}.png'))
            js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.15)
            assert c.dialog is None and dialog.result is not None,c.messages.showerror.call_args
            assert dialog.result.bindings['date']['column']=='C'
            assert dialog.result.bindings['t']['column']=='A'
            assert not (Path(temporary)/'profiles.json').exists()
    assert not errors,errors
    print('PASS: workbook roles, units, measurement/calculated types, bounded/reopenable dropdowns, confirmation, no settings writes')
finally:
    window.close();application.processEvents()
