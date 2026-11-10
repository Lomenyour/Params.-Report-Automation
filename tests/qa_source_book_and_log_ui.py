"""Actual Qt/HTML controls, full live journal and source-book dispatch isolation."""
from pathlib import Path
import json
import os
import sys
import time
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
sys.path.insert(0,str(ROOT/'scr'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QTextCursor
from PySide6.QtWidgets import QApplication
from desktop_app import DesktopWindow
from log_viewer import LogViewer

# Use Windows font rendering while keeping both test windows unexposed.
_log_init=LogViewer.__init__
def hidden_log(self,controller):
    _log_init(self,controller)
    self.setAttribute(Qt.WA_DontShowOnScreen,True)
LogViewer.__init__=hidden_log

application=QApplication([])
window=DesktopWindow()
window.setAttribute(Qt.WA_DontShowOnScreen,True)
window.show()
errors=[]
window.page.javaScriptConsoleMessage=lambda level,message,line,source:errors.append(message)


def pump(seconds=.05):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        application.processEvents();time.sleep(.005)


def js(code):
    result=[]
    window.page.runJavaScript(code,lambda value:result.append(value))
    end=time.monotonic()+8
    while not result and time.monotonic()<end:pump(.02)
    assert result,code
    return result[0]


try:
    end=time.monotonic()+30
    while not window.controller.ready and time.monotonic()<end:pump(.05)
    c=window.controller
    assert c.ready,errors
    assert js("document.querySelector('[data-action=sourceBook]').disabled")
    station=c.station_repository.get_station('izhevsk_tec')
    c.station_var.set(station.name)
    c.unit_var.set(c.station_repository.list_turbines(station.id)[0].name)
    c.selected_file=ROOT/'data/qa_source_workbook_20261110/original.xlsx'
    c.selected_raw_file=ROOT/'data/qa_source_workbook_20261110/raw.csv'
    c.selected_raw_sheet.set('CSV')
    c.raw_sheet_combo.configure(values=['CSV'])
    c.calculation_mode.set('import')
    c._update_input_controls();pump()
    assert c.last_result is None
    assert not js("document.querySelector('[data-action=sourceBook]').disabled")
    assert js("document.querySelector('[data-action=excel]').disabled")
    for operation in ('calculation_running','export_running'):
        setattr(c,operation,True);c._update_input_controls();pump()
        assert js("document.querySelector('[data-action=sourceBook]').disabled")
        setattr(c,operation,False)
    c._update_input_controls();pump()
    # A source-book click never reaches start_calculation or tariff parsing.
    c._ensure_book_mapping=Mock(return_value=True)
    c.sensor_mappings=[];c.mapping_sheet='CSV'
    stat=c.selected_file.stat();c.mapping_book_stamp=(stat.st_mtime_ns,stat.st_size)
    stat=c.selected_raw_file.stat();c.mapping_source_stamp=(stat.st_mtime_ns,stat.st_size)
    c.files.asksaveasfilename=Mock(return_value='')
    c.start_calculation=Mock();c._parse_tariff=Mock(side_effect=AssertionError('tariffs'))
    js("document.querySelector('[data-action=sourceBook]').click()")
    pump(.1)
    c.files.asksaveasfilename.assert_called_once()
    c.start_calculation.assert_not_called();c._parse_tariff.assert_not_called()
    snapshot=object();c.last_result=snapshot
    c.messages.showinfo=Mock();c.messages.showwarning=Mock();c.messages.showerror=Mock()
    c.files.asksaveasfilename=Mock(return_value=str(ROOT/'build_test/source_book_ui_result.xlsx'))
    c.station_repository.save_tariffs=Mock()
    with patch('source_workbook.save_source_workbook',return_value={'warnings':[]}) as save:
        c.dispatch('sourceBook','{}')
        end=time.monotonic()+5
        while c.export_running and time.monotonic()<end:pump(.03)
        assert not c.export_running and not c.source_book_running
        save.assert_called_once();c.messages.showinfo.assert_called_once()
    assert c.last_result is snapshot and not c.has_calculation_run
    c.start_calculation.assert_not_called();c._parse_tariff.assert_not_called()
    c.station_repository.save_tariffs.assert_not_called()
    with patch('source_workbook.save_source_workbook',side_effect=RuntimeError('Тестовая ошибка Excel')):
        c.dispatch('sourceBook','{}')
        end=time.monotonic()+5
        while c.export_running and time.monotonic()<end:pump(.03)
        assert not c.export_running and not c.source_book_running
        c.messages.showerror.assert_called_once()
    assert c.last_result is snapshot
    c.last_result=None;c._clear_log();c._update_input_controls()
    c._append_log(''.join(f'Строка {i}: полный журнал\n' for i in range(5000)))
    opened=js("document.querySelector('.gtu-journal').open")
    js("document.querySelector('[data-action=fullLog]').click()")
    pump(.1)
    assert js("document.querySelector('.gtu-journal').open")==opened
    viewer=c.log_viewer
    assert viewer.isVisible() and viewer.text.toPlainText()==c.logs
    assert QFontMetrics(viewer.text.font()).inFontUcs4(ord('Ж')),viewer.text.font().family()
    assert viewer.text.document().blockCount()==5001
    c._append_log('Живая строка\n');pump()
    assert viewer.text.toPlainText().endswith('Живая строка\n')
    viewer.text.verticalScrollBar().setValue(0)
    c._append_log('Ещё строка\n');pump()
    assert viewer.text.verticalScrollBar().value()==0
    viewer.search.setText('Строка 4321:');viewer.find_next()
    assert viewer.text.textCursor().selectedText()=='Строка 4321:'
    viewer.copy_all()
    assert application.clipboard().text()==c.logs
    # Full log remains accessible while the period-selection dialog is active.
    viewer.close();c.period_request={'event':Mock()}
    c.dispatch('fullLog','{}');assert c.log_viewer is viewer and viewer.isVisible()
    c.period_request=None
    c._clear_log();pump();assert viewer.text.toPlainText()==''
    c._append_log('Книга с новой выгрузкой\nExcel продлил формулы\n');pump()
    viewer.search.clear()
    output=ROOT/'build_test/source_book_log_ui';output.mkdir(parents=True,exist_ok=True)
    for width,height in ((900,600),(1200,800)):
        window.resize(width,height);pump(.15)
        js("document.querySelector('[data-action=sourceBook]').scrollIntoView({block:'center'})")
        bounds=json.loads(js("JSON.stringify((()=>{const a=document.querySelector('[data-action=sourceBook]').getBoundingClientRect(),b=document.querySelector('[data-action=fullLog]').getBoundingClientRect();return {source:{left:a.left,right:a.right,top:a.top,bottom:a.bottom},log:{left:b.left,right:b.right,top:b.top,bottom:b.bottom},width:innerWidth,height:innerHeight}})())"))
        for item in ('source','log'):
            rect=bounds[item]
            assert rect['left']>=0 and rect['right']<=bounds['width'] and rect['top']>=0 and rect['bottom']<=bounds['height'],bounds
        window.view.grab().save(str(output/f'workspace-{width}.png'))
    viewer.grab().save(str(output/'full-log.png'))
    assert not errors,errors
    print('PASS: source-book availability/guards; no analytics/tariffs; 5000 log lines, live append, search, copy, reopen and responsive UI')
finally:
    window.controller.source_book_running=False
    window.controller.period_request=None
    window.close();pump(.1)
