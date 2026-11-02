"""Run separately: py -X utf8 tests/qa_gas_and_ignore_ui.py. No real data or settings writes."""
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

def fill(section,key,value):
    js(f'''(()=>{{const section=document.querySelectorAll('.gtu-dialog details')[{section}],
      input=[...section.querySelectorAll('input')].find(x=>x.dataset.gasKey==={json.dumps(key)});
      input.value={json.dumps(value)};input.dispatchEvent(new Event('input',{{bubbles:true}}));}})()''')

try:
    end=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<end:pump(.05)
    assert window.controller.ready,errors
    c=window.controller;c.messages.showerror=Mock()
    from gas_composition import CH_METHOD
    from gas_passport import GasPassport
    dialog=GasPassportDialog(c,None,'izhevsk_tec','1','Ижевская ТЭЦ');show(dialog)
    assert js("document.querySelector('[data-gas-key=carbon_hydrogen_ratio]').readOnly")
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.1)
    assert c.dialog is dialog and not c.messages.showerror.called
    fill(0,'density_kg_per_nm3','0,7');fill(0,'q_lower_mj_per_nm3','35')
    fill(0,'component:Methane','1')
    ratio=js("Number(document.querySelector('[data-gas-key=carbon_hydrogen_ratio]').value)")
    assert abs(ratio-12.011/(4*1.008))<1e-8
    fill(0,'component:Methane','0,9');fill(0,'component:Ethane','0,1')
    ratio=js("Number(document.querySelector('[data-gas-key=carbon_hydrogen_ratio]').value)")
    assert abs(ratio-12.011*1.1/(1.008*4.2))<1e-8
    # Inert dilution does not change C/H of the combustible fraction.
    fill(0,'component:Methane','0,45');fill(0,'component:Ethane','0,05');fill(0,'component:CarbonDioxide','0,5')
    assert abs(js("Number(document.querySelector('[data-gas-key=carbon_hydrogen_ratio]').value)")-ratio)<1e-8
    for _ in range(2):js("[...document.querySelectorAll('button')].find(x=>x.textContent==='+ Добавить паспорт').click()")
    for index in (1,2):
        fill(index,'density_kg_per_nm3','0,7');fill(index,'q_lower_mj_per_nm3','35');fill(index,'component:Methane','1')
    js("document.querySelectorAll('.gtu-dialog details').forEach((section,i)=>{const dates=section.querySelectorAll('input[type=datetime-local]');dates[0].value=`2026-0${i+1}-01T00:00`;dates[1].value=`2026-0${i+2}-01T00:00`;})")
    window.resize(900,600);pump(.1)
    js("document.querySelector('.gtu-dialog-body').scrollTop=0");pump(.1)
    (ROOT/'build_test').mkdir(exist_ok=True)
    window.view.grab().save(str(ROOT/'build_test/automatic-ch-900.png'))
    # A client cannot override the computed result by tampering with readonly DOM.
    js("document.querySelector('[data-gas-key=carbon_hydrogen_ratio]').value='999'")
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.2)
    assert c.dialog is None and isinstance(dialog.result,GasPassportHistory) and len(dialog.result.entries)==3
    assert abs(dialog.result.entries[0].carbon_hydrogen_ratio-ratio)<1e-8
    assert all(entry.carbon_hydrogen_ratio_method==CH_METHOD for entry in dialog.result.entries)
    # Legacy data are previewed but are not silently rewritten on cancellation.
    legacy=GasPassport.from_dict({'station_id':'syz_tec','unit':'10','density_kg_per_nm3':.7,
        'q_lower_mj_per_nm3':35,'carbon_hydrogen_ratio':8,'components':{'Methane':1}})
    legacy_dialog=GasPassportDialog(c,legacy,'syz_tec','10','СызТЭЦ');show(legacy_dialog)
    assert js("document.querySelector('.gtu-dialog-body').textContent.includes('Ранее сохранено C/H = 8')")
    c.resolve_dialog({'action':'cancel'});pump(.1)
    assert legacy.carbon_hydrogen_ratio==8
    ignored=MappingDialog(c,[SensorMapping('PF','AM',source_unit='Па',target_unit='Гц')],
                          {'AM':'cosφ'},['PF'],set(),'izhevsk_tec');show(ignored)
    select('Колонка для PF','Не учитывать')
    assert js("[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Исходные единицы PF').disabled")
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.2)
    assert c.dialog is None and ignored.result[0].status=='ignored' and not ignored.result[0].target
    restored=MappingDialog(c,ignored.result,{'AM':'cosφ'},['PF'],set(),'izhevsk_tec');show(restored)
    assert js("[...document.querySelectorAll('.gtu-dialog input')].find(x=>x.getAttribute('aria-label')==='Колонка для PF').value")=='Не учитывать'
    select('Колонка для PF','AM — cosφ')
    select('Исходные единицы PF','о.е.');select('Единицы назначения PF','о.е.')
    js("document.querySelector('.gtu-dialog-actions .gtu-primary').click()");pump(.2)
    assert c.dialog is None and restored.result[0].status=='mapped'
    assert not errors,errors
    print('PASS: live readonly C/H, molar composition and inert dilution, three passports, tamper-proof server result, legacy cancellation, ignored/unignored channel')
finally:
    window.close();application.processEvents()
