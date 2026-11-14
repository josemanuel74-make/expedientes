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


# Only affirmative, pupil-subject formulations are recognized. Unmatched accounts
# remain explicitly pending review rather than being guessed from isolated words.
BEHAVIOR_RULES = (
    ('disruption', 'Interrumpe el desarrollo de las clases',
     r'(?:interrupciones continuas|interrumpe(?: continuamente)? (?:la clase|las clases)|interrumpio la actividad de clase)'),
    ('leaves', 'Abandona el aula durante las sesiones',
     r'(?:se va del aula en mitad de la sesion|(?:sale|se sale|abandona) (?:de )?(?:el aula|la clase|clase)(?: sin permiso| durante la clase)?)'),
    ('corridors', 'Permanece en los pasillos sin entrar a clase',
     r'(?:no entra a clase y se queda en los pasillos(?: del centro)?|se queda en los pasillos sin entrar a clase)'),
    ('late', 'Llega tarde a clase',
     r'(?:llega tarde a clase(?: continuamente| de forma reiterada)?|retrasos (?:continuos|reiterados))'),
    ('mobile', 'Utiliza el móvil en clase',
     r'(?:usa|utiliza|uso de|utilizacion de) (?:el )?(?:movil|telefono movil)(?: en clase| en el aula)?'),
    ('ignores', 'Desatiende las indicaciones del profesorado',
     r'(?:no (?:hace|hacer) caso a (?:la profesora|el profesor)|desobedece (?:a la profesora|al profesor)|se le pide que lo apague y no hace caso)'),
    ('disrespect', 'Se dirige de forma inadecuada al profesorado',
     r'(?:hablarle mal a (?:la profesora|el profesor)|habla mal (?:a la profesora|al profesor)|falta al respeto (?:a la profesora|al profesor))'),
    ('refusal', 'Se niega a realizar las actividades propuestas',
     r'(?:se niega|se nego) a (?:realizar|hacer) (?:la actividad propuesta|las actividades propuestas|las tareas propuestas)'),
    ('fight', 'Participa en una pelea',
     r'se pelea (?:con (?:otro alumno|otra alumna|un companero|una companera)|en clase)(?: a punetazos)?'),
    ('graffiti_staff', 'Consta la realización de pintadas con insultos dirigidos a la Jefatura de Estudios',
     r'(?:realiza |hace )?pintadas con insultos (?:a|dirigidos a) (?:los )?jefes de estudios'),
)


def report_behaviors(report: dict) -> tuple[set[str], bool]:
    if any(mark in report['incident'] for mark in ('"', '\u00ab', '\u00bb', '\u201c', '\u201d')):
        return set(), True
    found = set()
    pending = False
    sentences = re.split(r'[.!?;\n]+', report['incident'])
    for sentence in sentences:
        text = normalized(sentence)
        if not text:
            continue
        # These are prior corrections, not new allegations to draft as charges.
        if re.fullmatch(r'expulsion(?: de \d+ dias)?|amonestacion', text):
            continue
        text = re.sub(r'^(?:el alumno|la alumna) ', '', text)
        matches = {key for key, _, pattern in BEHAVIOR_RULES if re.fullmatch(pattern, text)}
        found.update(matches)
        pending |= not bool(matches)
    # Do not resolve pronouns or carry a subject across an unrecognized sentence.
    # Such accounts may describe witnesses, another pupil, or a denial.
    if pending:
        return set(), True
    return found, not bool(found)


def draft_facts(reports: list[dict]) -> str:
    if not reports:
        raise ValueError('Selecciona al menos un parte.')
    ordered = sorted(reports, key=lambda r: (r['date'], r['source_row']))
    first, last = (date.fromisoformat(r['date']).strftime('%d/%m/%Y') for r in (ordered[0], ordered[-1]))
    period = f'el día {first}' if first == last else f'entre el {first} y el {last}'
    count = len(ordered)
    opening = (f'Consta un parte de disciplina {period}.'
               if count == 1 else
               f'Acumulación de partes de disciplina: {count} en total, {period}.')
    behaviors = set()
    pending = 0
    for report in ordered:
        found, needs_review = report_behaviors(report)
        behaviors.update(found)
        pending += needs_review
    phrases = [description for key, description, _ in BEHAVIOR_RULES if key in behaviors]
    if 'mobile' in behaviors and 'ignores' in behaviors:
        phrases.remove('Utiliza el móvil en clase')
        phrases.remove('Desatiende las indicaciones del profesorado')
        phrases.insert(min(3, len(phrases)), 'Utiliza el móvil en clase y desatiende las indicaciones del profesorado')
    body = '. '.join(phrases)
    if body:
        body = 'Según los partes seleccionados, ' + body[0].lower() + body[1:] + '.'
    else:
        body = 'Pendiente de redactar los comportamientos concretos a partir de los relatos originales.'
    if pending:
        body += f" Quedan detalles de {pending} {'parte' if pending == 1 else 'partes'} pendientes de revisión y concreción en este borrador."
    return f'{body} {opening}'
