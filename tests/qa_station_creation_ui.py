"""Real station-addition button/dialog, immediate selection and passport binding."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time
from unittest.mock import Mock

os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scr'))
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from desktop_app import DesktopWindow
from desktop_controller import GasPassportDialog
from station_creation_ui import StationCreationDialog
from station_profiles import JsonStationRepository,catalog_path,station_sort_key

app=QApplication([])
window=DesktopWindow()
window.setAttribute(Qt.WA_DontShowOnScreen,True)
window.show()
_init=StationCreationDialog.__init__
def hidden(self,*args,**kwargs):
    _init(self,*args,**kwargs)
    self.setAttribute(Qt.WA_DontShowOnScreen,True)
StationCreationDialog.__init__=hidden


def pump(seconds=.05):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.005)


def js(code):
    result=[];window.page.runJavaScript(code,lambda value:result.append(value))
    end=time.monotonic()+8
    while not result and time.monotonic()<end:pump(.02)
    assert result,code
    return result[0]


try:
    end=time.monotonic()+25
    while not window.controller.ready and time.monotonic()<end:pump()
    c=window.controller;assert c.ready
    with tempfile.TemporaryDirectory() as folder:
        store=Path(folder)/'user_stations.json'
        c.station_repository=JsonStationRepository(catalog_path(),catalog_store=store)
        c.stations_by_name={row.name:row for row in c.station_repository.list_stations()}
        c.selected_file=ROOT/'data/КазТЭЦ-1.xlsb'
        c._update_input_controls();pump()
        c._calculation_worker=Mock(side_effect=AssertionError('analytics'))
        assert not js("document.querySelector('[data-action=addStation]').disabled")
        assert not js("[...document.querySelectorAll('button')].some(x=>x.textContent.includes('Добавить ГТ'))")
        snapshot=object();c.last_result=snapshot
        checked=[]
        def cancel():
            dialog=window.findChildren(StationCreationDialog)[-1]
            checked.append(dialog.aliases.text()=='КазТЭЦ-1' and dialog.number.text()=='')
            dialog.reject()
        QTimer.singleShot(150,cancel)
        c.dispatch('addStation','{}')
        assert checked==[True] and not store.exists() and c.last_result is snapshot
        errors=[]
        _warning=QMessageBox.warning
        QMessageBox.warning=lambda *args,**kwargs:errors.append(args[2])
        try:
            def fill():
                dialog=window.findChildren(StationCreationDialog)[-1]
                dialog.accept();assert errors and not store.exists()
                dialog.name.setText('Тестовая Казанская ТЭЦ-1')
                dialog.genitive.setText('Тестовой Казанской ТЭЦ-1')
                dialog.number.setText('1')
                dialog.model.setText('Тестовая модель')
                dialog.grab().save(str(ROOT/'build_test/station_creation_form.png'))
                dialog.accept()
            QTimer.singleShot(150,fill)
            js("document.querySelector('[data-action=addStation]').click()")
            end=time.monotonic()+5
            while not store.exists() and time.monotonic()<end:pump()
            pump(.1)
        finally:QMessageBox.warning=_warning
        assert store.exists()
        assert c.station_var.get()=='Тестовая Казанская ТЭЦ-1'
        assert c.unit_var.get()=='ГТУ-1' and c.last_result is None
        assert js("document.querySelector('#station').value")==c.station_var.get()
        assert js("document.querySelector('#unit').value")=='ГТУ-1'
        assert not js("document.querySelector('[data-action=gasPassport]').disabled")
        names=json.loads(js("JSON.stringify([...document.querySelector('#station').options].map(x=>x.value).filter(Boolean))"))
        assert names==sorted(names,key=station_sort_key)
        station=c.station_repository.get_station(c._selected_turbine().station_id)
        passport=GasPassportDialog(c,None,station.id,'1',station.name)
        assert station.name in passport.payload['title']
        assert all(field['value']=='' for field in passport.payload['entries'][0]['fields'])
        assert passport.station_id==station.id and passport.unit=='1'
        # Payload construction does not open or save a passport.
        passport.destroy()
        c._calculation_worker.assert_not_called()
        for operation in ('calculation_running','export_running'):
            setattr(c,operation,True);c._update_input_controls();pump()
            assert js("document.querySelector('[data-action=addStation]').disabled")
            setattr(c,operation,False)
        c._update_input_controls();pump()
        for width,height in ((900,600),(1200,800)):
            window.resize(width,height);pump(.1)
            rect=json.loads(js("JSON.stringify((()=>{const r=document.querySelector('[data-action=addStation]').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}})())"))
            assert 0<=rect['left']<rect['right']<=width and 0<=rect['top']<rect['bottom']<=height,rect
            window.view.grab().save(str(ROOT/f'build_test/station_creation_{width}.png'))
        reloaded=JsonStationRepository(catalog_path(),catalog_store=store)
        assert reloaded.get_station(station.id)==station
        print('PASS: one Add Station button; modal validation/cancel/save; sorted names; selected station/GT; empty linked passport; reload; no analytics')
finally:window.close();pump(.1)
