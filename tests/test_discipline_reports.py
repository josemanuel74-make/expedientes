import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from disciplinarios.app import create_app
from disciplinarios.db import close_db
from disciplinarios.discipline import draft_facts, matching_reports
from tools.discipline_excel import read_reports


def example_workbook():
    book = Workbook()
    book.active.title = 'Resumen'
    book.active.append(['No es un parte'])
    headers = ['Fecha', 'Alumno/a', 'Curso', 'Unidad', 'Expediente', 'Incidente', 'Conductas negativas', 'Correcciones aplicadas']
    sheet = book.create_sheet('01-10-2026')
    sheet.append(headers)
    row = ['01/10/2026', 'Perez Garcia, Ana', 'ESO', 'E_1A', 100, 'Interrumpió la actividad de clase.', 'Interrupciones registradas', '--']
    sheet.append(row)
    sheet.append(row)
    sheet.append(['01/10/2026', 'Lopez, Luis', 'ESO', 'E_1A', 200, 'Incidente de otro alumno.', 'Otra conducta', 'Amonestación'])
    sheet.append(['01/10/2026', 'Perez Garcia, Ana', 'ESO', 'E_1B', 100, 'Registro de otra unidad.', 'Otra unidad', '--'])
    other = book.create_sheet('02-10-2026')
    other.append(headers)
    other.append(['02/10/2026', 'Perez Garcia, Ana', 'ESO', 'E_1A', 100, 'Se negó a realizar la actividad propuesta.', 'Conducta registrada', '--'])
    old = book.create_sheet('01-06-2026')
    old.append(headers)
    old.append(row)
    book.create_sheet('expulsiones').append(row)
    data = io.BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


class DisciplineReaderTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = read_reports(example_workbook(), '2026-2027', '2026-10-02T12:00:00+00:00')
        self.student = {'full_name': 'Ana Pérez García', 'group_name': 'E_1A'}

    def test_daily_sheets_only_and_exact_duplicates_removed(self):
        self.assertEqual(len(self.snapshot['reports']), 4)
        reports, excluded = matching_reports(self.snapshot, self.student)
        self.assertEqual(len(reports), 2)
        self.assertEqual(excluded, 1)
        self.assertTrue(all(report['unit'] == 'E_1A' for report in reports))

    def test_all_dates_and_ambiguous_school_record(self):
        reports, _ = matching_reports(self.snapshot, self.student)
        self.assertEqual(len(reports), 2)
        reports[0]['pupil_record'] = 'different-record'
        with self.assertRaises(ValueError):
            matching_reports(self.snapshot, self.student)

    def test_draft_summarizes_selected_parts_without_copying_or_prior_corrections(self):
        reports, _ = matching_reports(self.snapshot, self.student)
        reports[0]['correction'] = 'Sanción anterior que no debe proponerse'
        draft = draft_facts([reports[0]])
        self.assertIn('01/10/2026', draft)
        self.assertIn('consta un parte', draft)
        self.assertNotIn(reports[0]['incident'], draft)
        self.assertNotIn('02/10/2026', draft)
        self.assertNotIn(reports[1]['incident'], draft)
        self.assertNotIn(reports[0]['correction'], draft)

    def test_generic_narrative_uses_only_structured_categories(self):
        reports, _ = matching_reports(self.snapshot, self.student)
        reports[0]['conduct'] = 'Conductas contrarias a las normas de convivencia.Contraria'
        reports[1]['conduct'] = 'Falta de colaboración sistemática en la realización de las actividades.Contraria'
        reports[0]['incident'] = 'No hubo agresión ni daños.'
        draft = draft_facts(reports)
        self.assertIn('constan 2 partes', draft)
        self.assertIn('entre el 01/10/2026 y el 02/10/2026', draft)
        self.assertIn('incumplimiento de las normas', draft)
        self.assertIn('falta de colaboración', draft)
        self.assertNotIn('agresión', draft)
        self.assertNotIn('daños', draft)
        self.assertIn('sin anticipar una sanción', draft)


class DisciplineApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.snapshot = read_reports(example_workbook(), '2026-2027', '2026-10-02T12:00:00+00:00')
        self.source = self.root / 'reports.json'
        self.source.write_text(json.dumps(self.snapshot))
        with patch('disciplinarios.app.init_app'):
            self.app = create_app()
        self.app.config.update(TESTING=True, DATABASE=str(self.root / 'test.sqlite3'),
                               SESSION_COOKIE_SECURE=False, DISCIPLINE_REPORTS_PATH=str(self.source))
        self.app.teardown_appcontext(close_db)
        self.db = sqlite3.connect(self.app.config['DATABASE'])
        self.addCleanup(self.db.close)
        self.db.executescript(Path('disciplinarios/schema.sql').read_text())
        self.db.execute("INSERT INTO users (id, username, role) VALUES (1, 'admin', 'admin'), (2, 'teacher', 'instructor')")
        self.db.executemany("INSERT INTO students (id, full_name, course_name, group_name, guardians_name) VALUES (?, ?, 'ESO', 'E_1A', 'Tutor')", [(1, 'Ana Pérez García'), (2, 'Luis Lopez')])
        self.db.commit()
        self.client = self.app.test_client()
        self.login(1)

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user_id=user_id, csrf_token='test')

    def draft(self, ids, source=None, csrf=True):
        return self.client.post('/api/students/1/discipline-draft',
                                json={'report_ids': ids, 'source_sha256': source or self.snapshot['source_sha256']},
                                headers={'X-CSRF-Token': 'test'} if csrf else {})

    def test_lookup_and_selected_draft_leave_cases_unsaved(self):
        response = self.client.get('/api/students/1/discipline-reports')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['reports']), 2)
        report = response.json['reports'][0]
        response = self.draft([report['id']])
        self.assertEqual(response.status_code, 200)
        self.assertIn('01/10/2026', response.json['draft'])
        self.assertNotIn(report['incident'], response.json['draft'])
        self.assertEqual(response.json['student_id'], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM cases').fetchone()[0], 0)

    def test_other_students_records_cannot_be_injected(self):
        other = next(r for r in self.snapshot['reports'] if r['student_name'] == 'Lopez, Luis')
        self.assertEqual(self.draft([other['id']]).status_code, 400)
        self.assertEqual(self.draft(['invented']).status_code, 400)

    def test_csrf_and_admin_role_required(self):
        report = self.snapshot['reports'][0]
        self.assertEqual(self.draft([report['id']], csrf=False).status_code, 403)
        self.login(2)
        self.assertEqual(self.client.get('/api/students/1/discipline-reports').status_code, 302)
        self.assertEqual(self.draft([report['id']]).status_code, 302)

    def test_snapshot_change_requires_refresh(self):
        self.assertEqual(self.draft([self.snapshot['reports'][0]['id']], source='old-version').status_code, 409)

    def test_empty_or_excessive_selection(self):
        self.assertEqual(self.draft([]).status_code, 400)
        self.assertEqual(self.draft(['a'] * 51).status_code, 400)

    def test_lookup_returns_all_parts_even_with_old_date_query_or_over_200(self):
        report = matching_reports(self.snapshot, {'full_name': 'Ana Pérez García', 'group_name': 'E_1A'})[0][0]
        self.snapshot['reports'] = [{**report, 'id': str(n)} for n in range(205)]
        self.source.write_text(json.dumps(self.snapshot))
        response = self.client.get('/api/students/1/discipline-reports?start=2099-01-01&end=wrong')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['reports']), 205)

    def test_missing_snapshot_is_not_reported_as_zero_parts(self):
        self.source.unlink()
        response = self.client.get('/api/students/1/discipline-reports')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_duplicate_student_identity_is_rejected(self):
        self.db.execute("INSERT INTO students (full_name, course_name, group_name, guardians_name) VALUES ('Pérez García, Ana', 'ESO', 'E_1A', 'Tutor')")
        self.db.commit()
        self.assertEqual(self.client.get('/api/students/1/discipline-reports').status_code, 400)

    def test_case_creation_rejects_draft_from_different_student(self):
        response = self.client.post('/cases/new', data={'csrf_token': 'test', 'student_id': '2', 'facts_source_student_id': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.execute('SELECT count(*) FROM cases').fetchone()[0], 0)

    def test_create_page_contains_assistant(self):
        response = self.client.get('/cases/new')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Posibles cargos a partir de los partes'.encode(), response.data)
        self.assertIn(b'discipline-draft.js', response.data)
        self.assertNotIn(b'id="discipline-start"', response.data)
        self.assertNotIn(b'id="discipline-end"', response.data)


if __name__ == '__main__':
    unittest.main()
