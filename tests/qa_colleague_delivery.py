"""Extract the real ZIP outside the project and test its EXE and Word runtime."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_desktop_bundle import verify


def main():
    output=ROOT/'build_test/period_economics_qa_20261112'
    archive=ROOT/'app/delivery/GTU_Report_for_colleague.zip'
    with TemporaryDirectory(prefix='gtu_colleague_') as directory:
        temporary=Path(directory).resolve()
        # Verify the only directory that TemporaryDirectory will later remove.
        import tempfile
        assert temporary.parent==Path(tempfile.gettempdir()).resolve()
        assert temporary.name.startswith('gtu_colleague_')
        target=temporary/'Пакет коллеги'
        with ZipFile(archive) as packed:
            assert packed.testzip() is None
            for info in packed.infolist():
                name=PurePosixPath(info.filename)
                assert not name.is_absolute() and '..' not in name.parts and '\\' not in info.filename
                assert name.parts[0]=='GTU_Report'
                final=(target/info.filename).resolve()
                assert target.resolve() in final.parents
            packed.extractall(target)
            file_count=len(packed.infolist())
        bundle=target/'GTU_Report'
        assert not (bundle/'data').exists()
        assert not (bundle/'word_auto/reports').exists()
        modules=verify(bundle,'GTU_Report')
        print(f'PASS: extracted {file_count} files and verified {len(modules)} modules',flush=True)
        isolated=temporary/'empty_user_profile'
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tests/qa_rotor_startup.py'),
            '--executable',str(bundle/'GTU_Report.exe'),'--isolated-user-data',str(isolated),
            '--output',str(output/'colleague_startup.json')],check=True,timeout=90,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
        print(result.stdout.strip(),flush=True)
        startup_state=json.loads((output/'colleague_startup.json').read_text(encoding='utf-8'))
        base_catalog=json.loads((ROOT/'config/stations.json').read_text(encoding='utf-8'))
        assert startup_state['stations']==len(base_catalog['stations'])+1
        context=output/'synthetic_context.json'
        report=output/'colleague_report.docx';status=output/'colleague_word_check.json'
        env=os.environ.copy();env['LOCALAPPDATA']=str(isolated)
        system=Path(os.environ['SystemRoot'])/'System32'
        env['PATH']=';'.join(p for p in env.get('PATH','').split(';')
            if p and (Path(p)==system or not (Path(p)/'icuuc.dll').is_file()))
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=subprocess.SW_HIDE
        process=subprocess.run([str(bundle/'GTU_Report.exe'),'--check-word-report',str(context),
            str(report),str(status)],cwd=bundle,env=env,startupinfo=startup,timeout=90)
        assert process.returncode==0,status.read_text(encoding='utf-8') if status.exists() else process.returncode
        checked=json.loads(status.read_text(encoding='utf-8'))
        assert checked['ok'] and checked['frozen']
        assert checked['template_sha256']==hashlib.sha256((ROOT/'word_auto/templates/template_mapped.docx').read_bytes()).hexdigest()
        assert Path(checked['template']).is_relative_to(bundle)
        with ZipFile(report) as document:
            tree=ET.fromstring(document.read('word/document.xml'))
            text=''.join(node.text or '' for node in tree.iter() if node.tag.endswith('}t'))
            for value in ('ВНА ≥ 94','ВНА ≥ 91','51100','905200','Учтённая наработка'):
                assert value in text,value
            assert 'руб./нм3' in text and 'руб./тыс. м3' not in text
        report_data=dict(files=file_count,modules=len(modules),zip_test_ok=True,
            clean_profile=True,unicode_path=True,frozen_word_ok=True,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        (output/'colleague_delivery_qa.json').write_text(json.dumps(report_data,indent=2),encoding='utf-8')
        print('PASS: clean extracted EXE and packaged Word generator; local thresholds/annual values in DOCX; no external Python runtime required',flush=True)


if __name__=='__main__':main()
