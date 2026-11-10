"""Station reference fields survive JSON/Word export and keep snapshot identity."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd
from docx import Document

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scr'))
from reporting import build_report_data, save_report_data, load_report_data, generate_report_from_json
from station_profiles import JsonStationRepository, catalog_path


class StationWordFieldsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.repo=JsonStationRepository(catalog_path(), information_store=self.root/'contacts.json')

    def report(self,station=None):
        frame=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=2,freq='30min'),
                            'power':[70.,71.],'hours':[0.,.5],'hours_input':[0.,.5]})
        periods=pd.DataFrame([dict(period=1,date_start=frame.date.min(),date_end=frame.date.max())])
        return build_report_data(source_data=frame,rh_data=frame,periods_df=periods,
            boundary_table=None,delta_table=None,vna_results=[],economics_result={'table':pd.DataFrame()},
            nominal_hours={},gas_tariff=1.,electricity_tariff=2.,electricity_cost=1.,
            source_file='СызТЭЦ ГТ-11.xlsx',station=station)

    def template(self):
        path=self.root/'tags.docx'
        doc=Document()
        doc.add_paragraph('Станция: {{ station.name }}')
        doc.add_paragraph('Для {{ station.name_genitive }}')
        doc.add_paragraph('Контакты: {{ station.contact_persons }}')
        doc.add_paragraph('{% for name in station.contact_names %}{{ name }}; {% endfor %}')
        doc.save(path)
        return path

    def test_all_catalog_names_have_explicit_genitive_without_new_unit_numbers(self):
        stations=self.repo.list_stations()
        self.assertEqual(len(stations),33)
        self.assertTrue(all(s.name_genitive for s in stations))
        self.assertEqual(self.repo.get_station('izhevsk_tec').name,'Ижевская ТЭЦ')
        self.assertEqual(self.repo.get_station('izhevsk_tec').name_genitive,'Ижевской ТЭЦ')
        self.assertEqual(self.repo.get_station('perm_tec_9').name_genitive,'Пермской ТЭЦ-9')
        self.assertEqual(self.repo.get_station('mos_tec_21').name_genitive,'ТЭЦ-21')
        self.assertEqual(self.repo.get_station('nizhneturinskaya_gres').name_genitive,'Нижнетуринской ГРЭС')

    def test_names_survive_json_and_word_while_later_reference_edits_stay_out_of_snapshot(self):
        self.repo.save_station_contacts({'izhevsk_tec':['Иванов Иван Иванович','Петров П. П.']})
        info=self.repo.get_station_information('izhevsk_tec')
        source={'id':info.station.id,'name':info.station.name,
                'name_genitive':info.station.name_genitive,'contact_names':list(info.contact_names)}
        report=self.report(source)
        source['contact_names'].append('Сидоров С. С.')
        self.repo.save_station_contacts({'izhevsk_tec':['Сидоров С. С.']})
        self.assertEqual(report['station']['contact_names'],['Иванов Иван Иванович','Петров П. П.'])
        self.assertEqual(report['station']['contact_persons'],'Иванов Иван Иванович; Петров П. П.')
        path=save_report_data(report,self.root/'snapshot.json')
        self.assertEqual(load_report_data(path)['station'],report['station'])
        output=generate_report_from_json(path,self.template(),self.root/'output.docx')
        text='\n'.join(p.text for p in Document(output).paragraphs)
        self.assertIn('Станция: Ижевская ТЭЦ',text)
        self.assertIn('Для Ижевской ТЭЦ',text)
        self.assertIn('Контакты: Иванов Иван Иванович; Петров П. П.',text)
        self.assertNotIn('Сидоров',text)
        self.assertNotIn('СызТЭЦ',text)  # Filename never overrides selected station identity.
        self.assertNotIn('{{',text)

    def test_station_without_contacts_exports_empty_text_and_list(self):
        station=self.repo.get_station('mos_tec_12')
        report=self.report({'id':station.id,'name':station.name,'name_genitive':station.name_genitive})
        self.assertEqual(report['station']['contact_names'],[])
        self.assertEqual(report['station']['contact_persons'],'')

    def test_old_json_renders_new_tags_empty_without_looking_up_live_contacts(self):
        self.repo.save_station_contacts({'izhevsk_tec':['Иванов Иван Иванович']})
        legacy=self.report()
        legacy.pop('station')
        legacy['turbine']={'station_id':'izhevsk_tec','name':'ГТУ-1','number':'1','model':'PG6111FA'}
        path=self.root/'legacy.json'
        path.write_text(json.dumps(legacy,ensure_ascii=False),encoding='utf-8')
        loaded=load_report_data(path)
        self.assertEqual(loaded['station']['name_genitive'],'')
        output=generate_report_from_json(path,self.template(),self.root/'legacy.docx')
        text='\n'.join(p.text for p in Document(output).paragraphs)
        self.assertNotIn('Иванов',text)
        self.assertNotIn('Ижевской',text)
        self.assertNotIn('{{',text)

    def test_old_catalog_without_new_property_still_loads(self):
        data=json.loads(catalog_path().read_text(encoding='utf-8-sig'))
        for station in data['stations']:station.pop('name_genitive')
        path=self.root/'legacy_catalog.json'
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        self.assertEqual(JsonStationRepository(path).get_station('izhevsk_tec').name_genitive,'')


if __name__=='__main__':unittest.main()
