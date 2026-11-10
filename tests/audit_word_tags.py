"""Static DOCX tag inventory against the actual report context, without editing DOCX."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile

from docxtpl import DocxTemplate
from jinja2 import Environment, nodes
from jinja2.visitor import NodeVisitor
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scr'))
from reporting import build_report_data


def fields(value, prefix=''):
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            result |= fields(child, f'{prefix}.{key}' if prefix else key)
    elif isinstance(value, list):
        for child in value:
            result |= fields(child, 'period' if prefix == 'periods' else prefix+'[0]')
    else:
        result.add(prefix)
    return result


class References(NodeVisitor):
    def __init__(self):
        self.aliases = {}
        self.paths = set()

    def path(self, node):
        if isinstance(node, nodes.Name):
            return self.aliases.get(node.name, node.name)
        if isinstance(node, nodes.Filter):
            return self.path(node.node)
        if isinstance(node, nodes.Getattr):
            base = self.path(node.node)
            if base == 'periods' and re.fullmatch(r'p[1-9]\d*', node.attr):
                return 'period'
            return f'{base}.{node.attr}' if base else None
        if isinstance(node, nodes.Getitem):
            base = self.path(node.node)
            if base == 'periods':
                return 'period'
            if base and isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
                return f'{base}.{node.arg.value}'
            return base+'[0]' if base else None
        return None

    def visit_For(self, node):
        self.visit(node.iter)
        old = self.aliases.copy()
        if isinstance(node.target, nodes.Name):
            base = self.path(node.iter)
            if base:
                self.aliases[node.target.name] = 'period' if base == 'periods' else base+'[0]'
        for child in node.body:
            self.visit(child)
        self.aliases = old
        for child in node.else_:
            self.visit(child)

    def visit_Assign(self, node):
        self.visit(node.node)
        if isinstance(node.target, nodes.Name) and (path := self.path(node.node)):
            self.aliases[node.target.name] = path

    def generic_visit(self, node, *args, **kwargs):
        if isinstance(node, (nodes.Name, nodes.Getattr, nodes.Getitem)):
            path = self.path(node)
            if path and path.split('.')[0] not in {'loop', 'range', 'dict', 'namespace'}:
                self.paths.add(path)
        super().generic_visit(node, *args, **kwargs)


def context_schema():
    data = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=2, freq='30min'),
                         'power': [90., 90.], 'hours': [0., .5], 'hours_input': [0., .5]})
    periods = pd.DataFrame([dict(period=1, date_start=data.date.min(), date_end=data.date.max())])
    context = build_report_data(source_data=data, rh_data=data, periods_df=periods,
        boundary_table=None, delta_table=None, vna_results=[], economics_result={'table': pd.DataFrame()},
        nominal_hours={}, gas_tariff=0., electricity_tariff=0., electricity_cost=0.,
        manual_periods=[(data.date.min(), data.date.max())], station={'contact_names':['']})
    context['current_date'] = ''
    return fields(context)


def audit(template, available):
    engine = DocxTemplate(template)
    used = set()
    expressions = set()
    parts = []
    unknown = set()
    with ZipFile(template) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r'word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml', name):
                continue
            xml = engine.patch_xml(archive.read(name).decode('utf-8'))
            if '{{' not in xml and '{%' not in xml:
                continue
            parts.append(name)
            visitor = References()
            visitor.visit(Environment().parse(xml))
            used |= visitor.paths & available
            for path in visitor.paths - available:
                if path == 'periods':
                    continue
                if not any(field.startswith(path+'.') or field.startswith(path+'[') for field in available):
                    unknown.add(path)
            expressions |= set(re.findall(r'{{.*?}}|{%.*?%}', xml, re.S))
    return dict(template=str(template), sha256=hashlib.sha256(Path(template).read_bytes()).hexdigest(),
                parts=parts, available=sorted(available), used=sorted(used),
                unused=sorted(available-used), unknown=sorted(unknown), expressions=sorted(expressions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, default=ROOT/'word_auto/templates/template_mapped.docx')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    report = audit(args.template, context_schema())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.markdown:
        lines = ['# Теги Word — проверка 09.11.2026', '',
            'Проверена текущая пользовательская копия `word_auto/templates/template_mapped.docx`.',
            'DOCX не изменялся. `period.*` объединяет обращения в цикле, через `periods[0]`,',
            '`periods[-1]` и `periods.p1`. Наличие в условии также считается использованием.',
            'Это статический аудит: условный текст может не выводиться в конкретном отчёте.',
            '`source.selection_mode` и `source.selected_intervals[0].*` доступны только в ручном режиме.', '',
            f"Доступно полей: {len(report['available'])}; используются: {len(report['used'])}; "
            f"не используются: {len(report['unused'])}; неизвестных ссылок: {len(report['unknown'])}.", '',
            '## Не используются', '']
        lines += [f'- `{{{{ {name} }}}}`' for name in report['unused']]
        lines += ['', '## Используются', '']
        lines += [f'- `{{{{ {name} }}}}`' for name in report['used']]
        if report['unknown']:
            lines += ['', '## Неизвестные ссылки', '']
            lines += [f'- `{name}`' for name in report['unknown']]
        args.markdown.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('unused','unknown')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
