"""Check the packaged Word generator without Python installed on the target PC."""
import hashlib
import json
from pathlib import Path
import sys
import traceback
from zipfile import ZipFile


def check_word_report(arguments):
    if len(arguments) != 3:
        return 2
    source, output, status = map(lambda value: Path(value).resolve(), arguments)
    if len({source, output, status}) != 3 or output.suffix.lower() != '.docx' or status.suffix.lower() != '.json':
        return 2
    details = {'frozen': bool(getattr(sys, 'frozen', False)), 'executable': sys.executable, 'ok': False}
    try:
        from reporting import DEFAULT_TEMPLATE, generate_report_from_json
        if DEFAULT_TEMPLATE.resolve() in (output, status):
            raise ValueError('Самопроверка не должна перезаписывать шаблон.')
        generate_report_from_json(source, template_path=DEFAULT_TEMPLATE, output_path=output)
        with ZipFile(output) as document:
            assert document.testzip() is None
            for name in document.namelist():
                if name.endswith('.xml'):
                    text = document.read(name).decode('utf-8')
                    if '{{' in text or '{%' in text:
                        raise ValueError(f'В готовом Word остались теги: {name}')
        details.update(ok=True, template=str(DEFAULT_TEMPLATE), output=str(output),
            template_sha256=hashlib.sha256(DEFAULT_TEMPLATE.read_bytes()).hexdigest(),
            output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    except Exception as error:
        details.update(error=str(error), traceback=traceback.format_exc())
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if details['ok'] else 1
