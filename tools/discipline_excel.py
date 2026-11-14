"""Read the dated Fenicia worksheets without modifying the workbook."""

from datetime import date, datetime, timezone
import hashlib
import io
import json

from openpyxl import load_workbook


def text(value):
    if value is None or value in ('--', '-'):
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_reports(data: bytes, school_year: str, modified_at: str) -> dict:
    year, following = (int(v) for v in school_year.split('-'))
    if following != year + 1:
        raise ValueError('Curso escolar no válido.')
    first, last = date(year, 9, 1), date(following, 8, 31)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    reports = {}
    dated_sheets = 0
    try:
        for sheet in workbook:
            try:
                sheet_date = datetime.strptime(sheet.title, '%d-%m-%Y').date()
            except ValueError:
                continue
            if not first <= sheet_date <= last:
                continue
            dated_sheets += 1
            rows = sheet.iter_rows(values_only=True)
            headers = [text(v) for v in next(rows, ())]
            if not {'Alumno/a', 'Unidad', 'Incidente', 'Conductas negativas'}.issubset(headers):
                raise ValueError(f'Faltan columnas en la hoja {sheet.title}.')
            for row_number, row in enumerate(rows, 2):
                values = dict(zip(headers, row))
                if not text(values.get('Alumno/a')):
                    continue
                value = values.get('Fecha')
                if isinstance(value, datetime):
                    incident_date = value.date()
                elif isinstance(value, date):
                    incident_date = value
                elif text(value):
                    incident_date = datetime.strptime(text(value), '%d/%m/%Y').date()
                else:
                    incident_date = sheet_date
                if not first <= incident_date <= last:
                    continue
                report = {
                    'date': incident_date.isoformat(), 'student_name': text(values.get('Alumno/a')),
                    'unit': text(values.get('Unidad')), 'pupil_record': text(values.get('Expediente')),
                    'incident': text(values.get('Incidente')), 'conduct': text(values.get('Conductas negativas')),
                    'correction': text(values.get('Correcciones aplicadas')),
                }
                if not report['incident']:
                    raise ValueError(f'Parte sin incidente en {sheet.title}, fila {row_number}.')
                if any(len(value) > 16000 for value in report.values()):
                    raise ValueError('Un campo del parte supera el tamaño permitido.')
                key = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                if key not in reports:
                    reports[key] = {**report, 'id': key, 'source_sheet': sheet.title, 'source_row': row_number}
                if len(reports) > 100000:
                    raise ValueError('El libro contiene demasiados partes.')
    finally:
        workbook.close()
    if not dated_sheets:
        raise ValueError('No hay hojas diarias del curso configurado.')
    return {
        'version': 1, 'school_year': school_year,
        'source_sha256': hashlib.sha256(data).hexdigest(), 'source_modified_at': modified_at,
        'prepared_at': datetime.now(timezone.utc).isoformat(),
        'reports': sorted(reports.values(), key=lambda r: (r['date'], r['id'])),
    }
