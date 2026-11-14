"""Student-specific report lookup and factual drafts from the Fenicia snapshot."""

from datetime import date
import json
from pathlib import Path
import re
import unicodedata


def normalized(value: str) -> str:
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in value if not unicodedata.combining(c))))


def person_key(value: str) -> tuple[str, ...]:
    return tuple(sorted(normalized(value).split()))


def load_snapshot(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('No hay una copia de los partes disponible. Revisa su sincronización.')
    try:
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        if snapshot['version'] != 1 or not isinstance(snapshot['reports'], list):
            raise ValueError
        for key in ('source_sha256', 'school_year', 'source_modified_at'):
            if not isinstance(snapshot[key], str):
                raise ValueError
        if len(snapshot['reports']) > 100000:
            raise ValueError
        for report in snapshot['reports']:
            date.fromisoformat(report['date'])
            for key in ('id', 'student_name', 'unit', 'incident', 'conduct', 'correction', 'pupil_record', 'source_sheet'):
                if not isinstance(report[key], str) or len(report[key]) > 16000:
                    raise ValueError
            if not isinstance(report['source_row'], int):
                raise ValueError
        if len({r['id'] for r in snapshot['reports']}) != len(snapshot['reports']):
            raise ValueError
        return snapshot
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError('La copia de los partes no se puede leer. Revisa su sincronización.') from exc


def matching_reports(snapshot: dict, student, start: str = '', end: str = '') -> tuple[list[dict], int]:
    try:
        start, end = (date.fromisoformat(value).isoformat() if value else '' for value in (start, end))
    except ValueError as exc:
        raise ValueError('La fecha de consulta no es válida.') from exc
    if start and end and start > end:
        raise ValueError('La fecha inicial debe ser anterior o igual a la final.')
    name = person_key(student['full_name'])
    unit = normalized(student['group_name']).replace(' ', '')
    named = [r for r in snapshot['reports'] if person_key(r['student_name']) == name]
    matched = [r for r in named if unit and normalized(r['unit']).replace(' ', '') == unit]
    # Different school record numbers under one name/unit require human identification.
    records = {r['pupil_record'] for r in matched if r['pupil_record']}
    if len(records) > 1:
        raise ValueError('Hay más de una ficha escolar con ese nombre y unidad. Revisa la identidad antes de redactar.')
    result = [r for r in matched if (not start or r['date'] >= start) and (not end or r['date'] <= end)]
    result.sort(key=lambda r: (r['date'], r['source_sheet'], r['source_row']))
    return result, len(named) - len(matched)


def draft_facts(reports: list[dict]) -> str:
    if not reports:
        raise ValueError('Selecciona al menos un parte.')
    paragraphs = ['De los partes de disciplina seleccionados se desprenden las siguientes incidencias comunicadas, que se proponen para su esclarecimiento durante la instrucción del expediente:']
    for index, report in enumerate(sorted(reports, key=lambda r: (r['date'], r['source_row'])), 1):
        when = date.fromisoformat(report['date']).strftime('%d/%m/%Y')
        text = f"{index}. Según el parte de disciplina de fecha {when}, se comunica lo siguiente: {report['incident'].strip()}"
        if report['conduct'].strip():
            text += f"\nConducta consignada en el parte: {report['conduct'].strip()}"
        text += f"\nReferencia: hoja {report['source_sheet']}, fila {report['source_row']}."
        paragraphs.append(text)
    return '\n\n'.join(paragraphs)
