"""Compare packaged Rotor modules/assets with source and optional preserved-file hashes."""
import argparse
import hashlib
import json
import marshal
from pathlib import Path
import types

from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    return code.replace(co_filename='', co_consts=tuple(
        normalized(item) if isinstance(item, types.CodeType) else item for item in code.co_consts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preserved', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bundle = root/'dist_test/GTU_Report_Rotor_Test'
    executable = bundle/'GTU_Report_Rotor_Test.exe'
    archive = CArchiveReader(executable)
    pyz = archive.open_embedded_archive('PYZ.pyz')
    modules = []
    for source in sorted((root/'scr').glob('*.py')):
        if source.stem in archive.toc and archive.toc[source.stem][-1] == 's':
            actual = marshal.loads(archive.extract(source.stem))
        elif source.stem in pyz.toc:
            actual = pyz.extract(source.stem)
        else:
            continue
        assert normalized(actual) == normalized(compile(source.read_bytes(), str(source), 'exec')), source
        modules.append(source.stem)
    assert {'degradation_chart', 'pressure_chart', 'reporting', 'RH_raschet', 'rh_display'} <= set(modules)
    for source in (root/'scr/desktop_ui').iterdir():
        if source.is_file():
            assert source.read_bytes() == (bundle/'_internal/desktop_ui'/source.name).read_bytes(), source
    for name in ('stations.json', 'source_variants.json'):
        for directory in (bundle/'config', bundle/'_internal/config'):
            assert (root/'config'/name).read_bytes() == (directory/name).read_bytes(), directory/name
    for source in (root/'word_auto/templates').glob('*.docx'):
        for directory in (bundle/'word_auto/templates', bundle/'_internal/word_auto/templates'):
            assert source.read_bytes() == (directory/source.name).read_bytes(), directory/source.name
    if args.preserved:
        hashes = json.loads(args.preserved.read_text(encoding='utf-8'))
        for name, digest in hashes.items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    report = dict(modules=modules, ui_catalogs_templates_match=True,
                  preserved_match=bool(args.preserved), exe_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS: {len(modules)} modules; UI, catalogs, templates and preserved files match')


if __name__ == '__main__':
    main()
