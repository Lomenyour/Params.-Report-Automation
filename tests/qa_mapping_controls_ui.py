"""Run separately: py -X utf8 tests/qa_mapping_controls_ui.py. No real input files or settings writes."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scr'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from desktop_controller import GasPassportDialog, MappingDialog
from data_assembly import SensorMapping
from gas_passport import GasPassportHistory
from unit_conversions import unit_conversion
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
application=QApplication([])
window=DesktopWindow();window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);window.show()
errors=[]
window.page.javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)
def pump(seconds=.1):
    end=time.monotonic()+seconds
    while time.monotonic()<end:application.processEvents();time.sleep(.005)
def js(code):
    result=[];window.page.runJavaScript(code,lambda value:result.append(value))
    end=time.monotonic()+8
    while not result and time.monotonic()<end:pump(.02)
    assert result,code
    return result[0]
def show(dialog):
    window.controller.dialog=dialog
    window.controller.dialog_changed.emit(json.dumps(dialog.payload,ensure_ascii=False));pump(.15)

def select(label, value):
    assert js(f'''(()=>{{const input=[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==={json.dumps(label)});
      input.closest('.gtu-choice').querySelector('button').click();
      const option=[...document.querySelectorAll('.gtu-choice-popup [role=option]')].find(x=>x.textContent==={json.dumps(value)});
      if(!option)return false;option.dispatchEvent(new PointerEvent('pointerdown',{{bubbles:true,cancelable:true}}));return true;}})()'''),(label,value)
    pump(.05)

try:
    end=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<end:pump(.05)
    assert window.controller.ready,errors
    c=window.controller;c.messages.showerror=Mock()
    headers={'C':'Pатм, кПа','F':'Токр, °С','G':'ф, %','K':'ВЛО, Па','L':'ФГО, Па','M':'ФТО, Па',
             'N':'Δpнк, Па','O':'Pнк, Мбар','R':'Тнк, °С','W':'Ткк, °С','X':'Ркк, бар','Y':'ВНА',
             'AG':'Ргаза, МПа','AH':'tгаза, °С','AF':'Татк, °С','AM':'cosφ','AN':'n, Гц',
             'AO':'N, МВт','AS':'B, кг/с'}
    suggestions=[SensorMapping(f'CH{i}','') for i in range(23)]+[SensorMapping('LAST','AN',1/60,source_unit='об/мин',target_unit='Гц')]
    dialog=MappingDialog(c,suggestions,headers,[x.source for x in suggestions],set(),'izhevsk_tec');show(dialog)
    assert 'До уточнения' not in dialog.payload['choices']
    expected=len(dialog.payload['choices'])
    assert expected>10
    for width,height in ((900,600),(1200,800)):
        window.resize(width,height);pump(.15)
        js("document.querySelector('.gtu-dialog-body').scrollTop=100000")
        js("[...document.querySelectorAll('.gtu-choice input')].find(x=>x.getAttribute('aria-label')==='Колонка для LAST').closest('.gtu-choice').querySelector('button').click()")
        pump(.1)
        bounds=json.loads(js("JSON.stringify((()=>{const p=document.querySelector('.gtu-choice-popup'),r=p.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,sw:innerWidth,sh:innerHeight,count:p.querySelectorAll('[role=option]').length,direction:p.dataset.direction,scroll:p.scrollHeight>p.clientHeight}})())"))
        assert bounds['top']>=0 and bounds['left']>=0 and bounds['bottom']<=bounds['sh'] and bounds['right']<=bounds['sw'],bounds
        assert bounds['count']==expected and bounds['scroll'] and bounds['direction']=='up',bounds
        output=ROOT/'build_test';output.mkdir(exist_ok=True)
        window.view.grab().save(str(output/f'mapping-bottom-{width}.png'))
        js("(()=>{const i=[...document.querySelectorAll('.gtu-choice input')].find(x=>x.getAttribute('aria-label')==='Колонка для LAST');i.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()")
        pump(.05)
        assert not js("Boolean(document.querySelector('.gtu-choice-popup'))")
        js("[...document.querySelectorAll('.gtu-choice input')].find(x=>x.getAttribute('aria-label')==='Колонка для LAST').closest('.gtu-choice').querySelector('button').click()")
        assert js("document.querySelector('.gtu-choice-popup').querySelectorAll('[role=option]').length")==expected
        js("GtuChoiceField.close()")
    select('Колонка для LAST','AN — n, Гц')
    select('Колонка для LAST','AM — cosφ')
    select('Колонка для LAST','AN — n, Гц')
    for source,target,factor in [('мм вод. ст.','Па',9.80665),('кПа','Па',1000.),('мм рт. ст.','Па',133.322368),
            ('м³/ч','м³/с',1/3600),('об/мин','Гц',1/60),('дюйм вод. ст. (условн.)','Па',249.08891),
            ('дюйм вод. ст. (4 °C)','Па',249.082),('дюйм вод. ст. (60 °F)','Па',248.84),('дюйм рт. ст. (условн.)','Па',3386.389)]:
        select('Исходные единицы LAST',source);select('Единицы назначения LAST',target)
        actual=js("Number([...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Коэффициент для LAST').value)")
        assert abs(actual-factor)<1e-9,(source,target,actual)
    for source,target in [('K','°C'),('°C','K'),('°F','°C'),('°C','°F'),('°F','K'),('K','°F')]:
        select('Исходные единицы LAST',source);select('Единицы назначения LAST',target)
        multiplier,offset=unit_conversion(source,target)
        actual=js("Number([...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Коэффициент для LAST').value)")
        assert abs(actual-multiplier)<1e-10,(source,target,actual)
        text=js("document.querySelector('[aria-label=\"Преобразование для LAST\"]').textContent")
        assert 'x ×' in text and ('+' in text or '−' in text),(source,target,text)
        assert js("[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Коэффициент для LAST').checkValidity()")
    for width,height in ((900,600),(1200,800)):
        window.resize(width,height);pump(.1)
        js("document.querySelector('[aria-label=\"Преобразование для LAST\"]').scrollIntoView({block:'center'})")
        bounds=js("(()=>{const o=document.querySelector('[aria-label=\"Преобразование для LAST\"]'),r=o.getBoundingClientRect(),c=o.closest('td').getBoundingClientRect();return r.left>=c.left&&r.right<=c.right&&r.bottom<=c.bottom&&o.scrollWidth<=o.clientWidth})()")
        assert bounds,(width,height)
        window.view.grab().save(str(ROOT/'build_test'/f'mapping-temperature-{width}.png'))
    assert js("[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Исходные единицы LAST').readOnly")
    c.resolve_dialog({'action':'cancel'});pump(.1)
    # Confirm RPM, volume flow and a formerly deferred channel through real controls.
    mappings=[SensorMapping('SPEED','AN',1/60,source_unit='об/мин',target_unit='Гц'),
              SensorMapping('FLOW','AS',1/3600,source_unit='м³/ч',target_unit='м³/с'),
              SensorMapping('10MKA01FE006','',status='deferred'),
              SensorMapping('TEMP','R',5/9,source_unit='°F',target_unit='°C',offset=unit_conversion('°F','°C')[1])]
    dialog=MappingDialog(c,mappings,{'AN':'n, Гц','AS':'B, м³/с','AM':'cosφ','R':'Тнк, °C'},[x.source for x in mappings],set(),'izhevsk_tec');show(dialog)
    select('Колонка для 10MKA01FE006','AM — cosφ')
    select('Исходные единицы 10MKA01FE006','о.е.');select('Единицы назначения 10MKA01FE006','о.е.')
    select('Исходные единицы FLOW','кПа')
    assert not js("[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Коэффициент для FLOW').checkValidity()")
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.1)
    assert c.dialog is dialog and dialog.result is None
    assert not c.messages.showerror.called  # HTML rejected before dispatch; Python is checked separately.
    select('Исходные единицы FLOW','м³/ч')
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.2)
    assert c.dialog is None and len(dialog.result)==4
    assert dialog.result[2].target=='AM' and dialog.result[2].status=='mapped'
    assert abs(dialog.result[0].factor-1/60)<1e-12 and abs(dialog.result[1].factor-1/3600)<1e-12
    assert abs(dialog.result[3].factor-5/9)<1e-12 and abs(dialog.result[3].offset+160/9)<1e-12
    assert not errors,errors
    print('PASS: viewport bounds, upward popup, scrolling/End, reopening/reselection, unit dropdowns, inch pressures, six temperature directions and visible offsets, real affine confirmation, incompatible pair blocking, manual cosphi confirmation')
finally:
    window.close();application.processEvents()
