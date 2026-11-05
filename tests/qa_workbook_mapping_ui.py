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
from desktop_controller import BookMappingDialog,BookCorrectionsDialog
from workbook_profile import read_layout,suggestions,confirm
from test_workbook_profiles import fixture
from openpyxl import load_workbook

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

def wait_js(code):
    until=time.monotonic()+5
    while time.monotonic()<until:
        if js(code):return
        pump(.02)
    raise AssertionError(code)

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
    assert js("document.querySelector('.gtu-settings [data-action=\"bookMapping\"]')===null")
    assert js("document.querySelectorAll('.gtu-settings [data-action=\"corrections\"]').length===1")
    c=window.controller;c.messages.showerror=Mock()
    with tempfile.TemporaryDirectory() as temporary,patch('workbook_profile.profile_path',return_value=Path(temporary)/'profiles.json'):
        path=Path(temporary)/'book.xlsx';fixture(path)
        book=load_workbook(path);sheet=book['Данные'];sheet['N1']='kTN';sheet['R1']='Дополнительный датчик';sheet['S1']='kPη'
        for col,label in (('V','kφN'),('W','kPN'),('X','kΔPвхN'),('Y','kΔPвыхN')):sheet[f'{col}1']=label
        for row in (2,3,4):
            sheet[f'Q{row}']=f'=H{row}+1';sheet[f'R{row}']=0;sheet[f'S{row}']=1
            for col in ('V','W','X','Y'):sheet[f'{col}{row}']=1
            sheet[f'I{row}']=f'=H{row}/(V{row}*W{row}*X{row}*N{row}*Y{row})'
        book.save(path)
        layout=read_layout(path);rows=suggestions(layout,'station','1')
        for size in ((900,600),(1200,800)):
            window.resize(*size);pump(.1)
            dialog=BookMappingDialog(c,layout,rows,'station','1');c.dialog=dialog
            c.dialog_changed.emit(json.dumps(dialog.payload,ensure_ascii=False));pump(.15)
            assert js("document.querySelector('.gtu-dialog [aria-label=\"Параметр C\"]').value==='Дата и время'")
            assert js("document.querySelector('[aria-label=\"Параметр Q\"]')===null")
            assert js("!document.querySelector('.gtu-dialog-body').textContent.includes('Постоянные поправки из числовых столбцов')")
            assert js("document.querySelector('.gtu-book-table thead tr').cells.length===4")
            assert js("document.querySelectorAll('.gtu-book-table td small').length===0")
            assert js("document.querySelector('[aria-label=\"Тип C\"]').value==='Служебный'")
            assert js("""[...document.querySelectorAll('.gtu-book-table tbody tr')].every(row=>{
              const controls=[...row.querySelectorAll('.gtu-choice')].map(x=>x.getBoundingClientRect());
              return controls.length===3&&Math.max(...controls.map(x=>x.top))-Math.min(...controls.map(x=>x.top))<1;
            })""")
            choose('Параметр A','Вспомогательная колонка')
            choose('Параметр A','Температура перед компрессором')
            choose('Единицы A','°C')
            choose('Тип N','Измеренный');choose('Тип N','Расчётный')
            js("document.querySelector('[data-book-coefficients]').click()");pump(.05)
            wait_js("document.querySelector('.gtu-book-formulas').textContent.includes('Поправки!A1')")
            assert js("document.querySelector('.gtu-book-table').hidden")
            assert js("document.querySelector('.gtu-book-formulas').textContent.includes('Поправки!A1')")
            assert js("document.querySelector('.gtu-book-formulas').textContent.includes('0.8')")
            assert js("document.querySelectorAll('.gtu-book-formulas input').length===0")
            window.view.grab().save(str(ROOT/f'build_test/workbook-unified-coefficients-{size[0]}.png'))
            js("document.querySelector('[data-book-formulas]').click()");pump(.05)
            wait_js("document.querySelector('.gtu-book-formulas').textContent.includes('Nприв = Nизм / (kφN × kPN × kΔPвхN × kTN × kΔPвыхN)')")
            assert js("document.querySelector('.gtu-book-table').hidden&&!document.querySelector('.gtu-book-formulas').hidden")
            assert js("document.querySelector('.gtu-formula-table').textContent.includes('H2/(V2*W2*X2*N2*Y2)')")
            assert js("document.querySelectorAll('[aria-label^=\"Формула \"]').length===0")
            window.view.grab().save(str(ROOT/f'build_test/workbook-formulas-{size[0]}.png'))
            js("document.querySelector('[data-book-formulas]').click()");pump(.05)
            choose('Параметр N','Поправка температуры на КПД')
            js("document.querySelector('[data-book-formulas]').click()");pump(.05)
            wait_js("document.querySelector('.gtu-book-formulas').textContent.includes('Nприв = Nизм / (kφN × kPN × kΔPвхN × kTη × kΔPвыхN)')")
            js("document.querySelector('[data-book-formulas]').click()");pump(.05)
            choose('Параметр N','Поправка температуры на мощность')
            js("document.querySelector('[data-book-formulas]').click();document.querySelector('[data-book-formulas]').click()");pump(.15)
            assert js("!document.querySelector('.gtu-book-table').hidden&&document.querySelector('.gtu-book-formulas').hidden")
            assert js("document.querySelector('[aria-label=\"Параметр A\"]').value==='Температура перед компрессором'")
            js("document.querySelector('.gtu-dialog-body').scrollTop=0");pump(.05)
            window.view.grab().save(str(ROOT/f'build_test/workbook-mapping-{size[0]}.png'))
            js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.15)
            assert c.dialog is None and dialog.result is not None,c.messages.showerror.call_args
            assert dialog.result.bindings['date']['column']=='C'
            assert dialog.result.bindings['t']['column']=='A'
            assert 'Q' in dialog.result.recipes
            assert not (Path(temporary)/'profiles.json').exists()
        setup=confirm(layout,'station','1',rows,save=False)
        coefficients=BookCorrectionsDialog(c,setup);pump(.15)
        assert js("document.querySelector('.gtu-dialog').dataset.kind==='bookCorrections'")
        assert js("document.querySelector('.gtu-dialog-body').textContent.includes('Поправки!A1')")
        assert js("document.querySelectorAll('.gtu-dialog-body input').length===0")
        window.view.grab().save(str(ROOT/'build_test/workbook-coefficients-1200.png'))
        js("document.querySelector('.gtu-dialog-actions button').click()");pump(.1)
        assert c.dialog is None
    assert not errors,errors
    print('PASS: one sidebar entry, four aligned columns, formula/coefficient switching preserves mapping, read-only coefficients, bounded dropdowns, confirmation, no settings writes')
finally:
    window.close();application.processEvents()
