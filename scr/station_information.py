"""Local station contacts. Only names are stored, never phones or email."""
from datetime import datetime, timezone

from json_store import read_json, transaction, write_json


def _names(values):
    if not isinstance(values, (list, tuple)):
        raise ValueError('Контакты ТЭЦ должны быть списком ФИО.')
    result = []
    for name in values:
        if (not isinstance(name, str) or len(name.split()) < 2 or
                any(char.isdigit() for char in name) or '@' in name or '+' in name):
            raise ValueError('В справочнике контактов допускаются только ФИО, без телефонов и почты.')
        name = name.strip()
        if name not in result:
            result.append(name)
    return result


def read_information(path):
    data = read_json(path, {'schema_version': 1, 'contacts': {}, 'unassigned': {}})
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Неподдерживаемая версия справочника сведений о ТЭЦ.')
    for field in ('contacts', 'unassigned'):
        if not isinstance(data.get(field), dict):
            raise ValueError('Повреждён справочник сведений о ТЭЦ; файл не изменён.')
        for key, names in data[field].items():
            if not isinstance(key, str) or not key:
                raise ValueError('В справочнике контактов не указана ТЭЦ.')
            _names(names)
    return data


def update_contacts(path, contacts, *, unassigned=None, source=None):
    """Merge an explicitly matched import in one atomic write."""
    prepared = {key: _names(values) for key, values in contacts.items()}
    pending = {key: _names(values) for key, values in (unassigned or {}).items()}
    if any(not isinstance(key, str) or not key for key in (*prepared, *pending)):
        raise ValueError('Не указана ТЭЦ для контакта.')
    with transaction():
        data = read_information(path)
        for field, records in (('contacts', prepared), ('unassigned', pending)):
            for key, names in records.items():
                data[field][key] = _names([*data[field].get(key, []), *names])
        data['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if source is not None:
            data['source'] = dict(source)
        write_json(path, data)
