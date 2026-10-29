"""Verify packaged application code, UI, catalogs and editable templates."""
import argparse
import marshal
from pathlib import Path
import types
from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    return code.replace(co_filename='<source>', co_consts=tuple(
        normalized(value) if isinstance(value, types.CodeType) else value
        for value in code.co_consts))


def verify(bundle, exe_name=None):
    root = Path(__file__).resolve().parents[1]
    bundle = Path(bundle).resolve()
    archive = CArchiveReader(str(bundle / ((exe_name or bundle.name) + '.exe')))
    pyz = archive.open_embedded_archive('PYZ.pyz')
    matched = []
    for source in (root / 'scr').glob('*.py'):
        name = source.stem
        if name in archive.toc and archive.toc[name][-1] == 's':
            code = marshal.loads(archive.extract(name))
        elif name in pyz.toc:
            code = pyz.extract(name)
        else:
            continue
        assert normalized(code) == normalized(compile(source.read_text(encoding='utf-8'), str(source), 'exec')), f'Code mismatch: {name}'
        matched.append(name)
    assert {'app','desktop_app','desktop_controller','reporting','station_profiles'} <= set(matched)
    for relative in ('config/stations.json','_internal/config/stations.json'):
        assert (bundle / relative).read_bytes() == (root/'config/stations.json').read_bytes(), relative
    for source in (root/'scr/desktop_ui').iterdir():
        if source.is_file():
            assert (bundle/'_internal/desktop_ui'/source.name).read_bytes() == source.read_bytes(), source.name
    templates = [p for p in (root/'word_auto/templates').glob('*.docx') if not p.name.startswith('~$')]
    assert templates, 'No report template'
    for template in templates:
        for relative in ('word_auto/templates', '_internal/word_auto/templates'):
            assert (bundle/relative/template.name).read_bytes() == template.read_bytes(), f'Template mismatch: {relative}/{template.name}'
    assert list((bundle/'_internal').rglob('QtWebEngineProcess.exe'))
    assert not (bundle/'_internal/icuuc.dll').exists()
    print(f'PASS: {len(matched)} code modules, UI, both catalogs and {len(templates)} templates match sources')
    return matched


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle',type=Path)
    parser.add_argument('--exe-name')
    args = parser.parse_args()
    verify(args.bundle,args.exe_name)
