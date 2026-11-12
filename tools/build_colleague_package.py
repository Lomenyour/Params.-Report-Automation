"""Promote the verified Rotor bundle to a complete, clean colleague ZIP."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import psutil

from verify_desktop_bundle import verify

ROOT=Path(__file__).resolve().parents[1]


def checked(path):
    path=Path(path).resolve()
    if path==ROOT or ROOT not in path.parents:
        raise ValueError(f'Package path escapes project: {path}')
    return path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    source=checked(ROOT/'dist_test/GTU_Report_Rotor_Test')
    for process in psutil.process_iter(['name','exe']):
        if (process.info['name'] or '').lower()=='gtu_report.exe':
            executable=process.info['exe']
            if executable and ROOT/'app' in Path(executable).resolve().parents:
                raise RuntimeError('Close the colleague application before updating it.')
    modules=verify(source,'GTU_Report_Rotor_Test')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]
    stage=checked(ROOT/'build_test'/f'colleague_stage_{stamp}')
    backup=checked(ROOT/'archive_builds'/f'colleague_before_{stamp}')
    package=checked(stage/'GTU_Report')
    package.mkdir(parents=True)
    shutil.copy2(source/'GTU_Report_Rotor_Test.exe',package/'GTU_Report.exe')
    for relative in ('_internal','config','word_auto/templates'):
        shutil.copytree(source/relative,package/relative)
    shutil.copy2(ROOT/'app/README.txt',package/'README.txt')
    assert not (package/'data').exists()
    verify(package,'GTU_Report')

    # Keep the historical source/support folder current as requested. Copy only
    # public implementation/resources, never the developer's local profiles.
    support=[]
    for path in sorted((ROOT/'scr').glob('*.py')):
        support.append((path,ROOT/'app/src'/path.name))
    support.append((ROOT/'scr/native_source_excel.ps1',ROOT/'app/src/native_source_excel.ps1'))
    for path in sorted((ROOT/'scr/desktop_ui').iterdir()):
        if path.is_file():support.append((path,ROOT/'app/src/desktop_ui'/path.name))
    for name in ('stations.json','source_variants.json'):
        support.append((ROOT/'config'/name,ROOT/'app/config'/name))
    for path in (ROOT/'word_auto/templates').glob('*.docx'):
        if not path.name.startswith('~$'):support.append((path,ROOT/'app/word_auto/templates'/path.name))
    for origin,target in support:
        checked(target)
        if target.exists() and origin.read_bytes()!=target.read_bytes():
            saved=checked(backup/'support'/target.relative_to(ROOT/'app'))
            saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(origin,target)
        assert target.read_bytes()==origin.read_bytes()

    files=sorted(path for path in package.rglob('*') if path.is_file())
    archive=checked(stage/'GTU_Report_for_colleague.zip')
    with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6) as output:
        for path in files:output.write(path,Path('GTU_Report')/path.relative_to(package))
    with ZipFile(archive) as output:
        assert output.testzip() is None
        assert set(output.namelist())=={(Path('GTU_Report')/p.relative_to(package)).as_posix() for p in files}
    delivery_stage=checked(stage/'delivery/GTU_Report')
    shutil.copytree(package,delivery_stage)
    promotions=[(package,ROOT/'app/dist/GTU_Report'),
                (delivery_stage,ROOT/'app/delivery/GTU_Report'),
                (archive,ROOT/'app/delivery/GTU_Report_for_colleague.zip')]
    old_paths=[ROOT/'app/dist/GTU_Report.exe',ROOT/'app/delivery/GTU_Report.zip']
    previous={}
    for _,target in promotions:
        checked(target)
        if target.is_file():previous[str(target.relative_to(ROOT))]=digest(target)
    for target in old_paths:
        if target.is_file():previous[str(target.relative_to(ROOT))]=digest(target)
    completed=[]
    try:
        for incoming,target in promotions:
            target=checked(target);incoming=checked(incoming)
            saved=checked(backup/'packages'/target.relative_to(ROOT/'app'))
            if target.exists():
                saved.parent.mkdir(parents=True,exist_ok=True);target.rename(saved)
            target.parent.mkdir(parents=True,exist_ok=True)
            try:incoming.rename(target)
            except Exception:
                if saved.exists():saved.rename(target)
                raise
            completed.append((incoming,target,saved))
        for target in old_paths:
            target=checked(target)
            if target.exists():
                saved=checked(backup/'packages'/target.relative_to(ROOT/'app'))
                saved.parent.mkdir(parents=True,exist_ok=True);target.rename(saved)
    except Exception:
        for incoming,target,saved in reversed(completed):
            target.rename(incoming)
            if saved.exists():saved.rename(target)
        raise
    for relative,value in previous.items():
        assert digest(backup/'packages'/Path(relative).relative_to('app'))==value
    final=ROOT/'app/delivery/GTU_Report_for_colleague.zip'
    report=dict(source_modules=modules,files=len(files),bytes=final.stat().st_size,
        sha256=digest(final),archive=str(final),backup=str(backup),preserved_previous_files=previous,
        support_files=len(support))
    output=ROOT/'build_test/period_economics_qa_20261112/colleague_package.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'PASS: complete colleague ZIP, {len(files)} files, {final.stat().st_size} bytes; {final}')


if __name__=='__main__':main()
