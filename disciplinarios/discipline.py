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


def matching_reports(snapshot: dict, student) -> tuple[list[dict], int]:
    name = person_key(student['full_name'])
    unit = normalized(student['group_name']).replace(' ', '')
    named = [r for r in snapshot['reports'] if person_key(r['student_name']) == name]
    matched = [r for r in named if unit and normalized(r['unit']).replace(' ', '') == unit]
    # Different school record numbers under one name/unit require human identification.
    records = {r['pupil_record'] for r in matched if r['pupil_record']}
    if len(records) > 1:
        raise ValueError('Hay más de una ficha escolar con ese nombre y unidad. Revisa la identidad antes de redactar.')
    result = list(matched)
    result.sort(key=lambda r: (r['date'], r['source_sheet'], r['source_row']))
    return result, len(named) - len(matched)


def draft_facts(reports: list[dict]) -> str:
    if not reports:
        raise ValueError('Selecciona al menos un parte.')
    ordered = sorted(reports, key=lambda r: (r['date'], r['source_row']))
    first, last = (date.fromisoformat(r['date']).strftime('%d/%m/%Y') for r in (ordered[0], ordered[-1]))
    period = f'el día {first}' if first == last else f'entre el {first} y el {last}'
    count = len(ordered)
    opening = (f'Según la documentación examinada, consta un parte de disciplina referido a una incidencia comunicada {period}.'
               if count == 1 else
               f'Según la documentación examinada, constan {count} partes de disciplina relativos a incidencias comunicadas {period}.')
    # Summarize only structured source categories, never infer allegations from keywords in narratives.
    categories = (
        ('conductas contrarias a las normas', 'el incumplimiento de las normas de convivencia del centro'),
        ('conductas contrarias al plan', 'el incumplimiento del Plan de Convivencia'),
        ('falta de colaboracion sistematica', 'la falta de colaboración en las actividades propuestas'),
        ('la agresion grave fisica o moral', 'conductas registradas bajo la categoría de agresión o discriminación'),
        ('actos de indisciplina', 'conductas registradas bajo la categoría de indisciplina, injurias u ofensas'),
        ('actos injustificados que perturben', 'la alteración del desarrollo de las actividades del centro'),
        ('la reiteracion', 'la reiteración de conductas contrarias a las normas de convivencia'),
        ('danos graves causados', 'daños comunicados en instalaciones, materiales o bienes'),
    )
    summaries = []
    for marker, description in categories:
        n = sum(marker in normalized(r['conduct']) for r in ordered)
        if n:
            summaries.append(f"{description} ({n} {'parte' if n == 1 else 'partes'})")
    if summaries:
        joined = summaries[0] if len(summaries) == 1 else '; '.join(summaries[:-1]) + '; y ' + summaries[-1]
        body = f'Las anotaciones de conducta recogidas en los partes se refieren a {joined}. Estas menciones describen lo comunicado en la documentación de origen y no constituyen una calificación definitiva de los hechos.'
    else:
        body = 'La documentación recoge incidencias cuya naturaleza y circunstancias concretas deberán precisarse a partir de los relatos originales, sin atribuir en este resumen conductas que no estén expresamente identificadas.'
    closing = 'Se propone esclarecer estos hechos durante la instrucción, contrastando el contenido de los partes y recabando las manifestaciones y demás elementos que procedan. La responsabilidad del alumno y la valoración de las conductas quedan pendientes de dicha comprobación, sin anticipar una sanción.'
    dates = ', '.join(dict.fromkeys(date.fromisoformat(r['date']).strftime('%d/%m/%Y') for r in ordered))
    return '\n\n'.join((opening, body, closing, f'Fechas de los partes examinados: {dates}.'))
