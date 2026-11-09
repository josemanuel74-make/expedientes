import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from werkzeug.test import EnvironBuilder

from disciplinarios.app import create_app
from disciplinarios.db import close_db
from tools.auto_sync_teams import REMOTE_CLOSED_CASES
from tools.sync_teams import REMOTE_EXPORT


PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'


class FamilyUploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'instance').mkdir()
        with patch('disciplinarios.app.init_app'):
            self.app = create_app()
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False,
                               DATABASE=str(self.root / 'instance/disciplinarios.sqlite3'),
                               GENERATED_DOCS_DIR=str(self.root / 'generated_docs'))
        self.app.teardown_appcontext(close_db)
        self.db = sqlite3.connect(self.app.config['DATABASE'])
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript(Path('disciplinarios/schema.sql').read_text())
        self.db.executemany('INSERT INTO users (id, username, role, email) VALUES (?, ?, ?, ?)',
                            [(1, 'admin', 'admin', 'admin@example.test'),
                             (2, 'instructor', 'instructor', 'teacher@example.test'),
                             (3, 'other', 'instructor', 'other@example.test')])
        self.db.execute("INSERT INTO students (id, full_name, course_name, group_name, guardians_name) VALUES (1, 'Alumno prueba', 'ESO', '1A', 'Familia prueba')")
        self.db.execute("""INSERT INTO cases (id, case_number, student_id, status, fact_known_date,
            facts_summary, instructor_name, instructor_email, closed_at)
            VALUES (1, 'TEST-01', 1, 'cerrado', '2026-10-01', 'Prueba',
                    'Instructor prueba', 'teacher@example.test', '2026-10-01 00:00:00')""")
        folder = self.root / 'generated_docs/case-1'
        folder.mkdir(parents=True)
        self.original = folder / '07 - Vista y Audiencia.docx'
        self.original.write_bytes(b'original-docx')
        self.signed = folder / '07 - firmado-instructor.pdf'
        self.signed.write_bytes(PDF)
        self.db.execute("""INSERT INTO generated_documents
            (id, case_id, template_name, doc_number, output_path, created_by_user_id)
            VALUES (7, 1, '07 - Vista y Audiencia.docx', '07', ?, 2)""", (str(self.original),))
        self.db.execute("""INSERT INTO signature_requests (generated_document_id, signer_name,
            signer_email, signer_role, status, signed_pdf_path)
            VALUES (7, 'Instructor prueba', 'teacher@example.test', 'instructor', 'signed', ?)""", (str(self.signed),))
        self.db.commit()
        self.client = self.app.test_client()
        self.login(2)

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user_id=user_id, csrf_token='test')

    def add_document_11(self):
        folder = self.root / 'generated_docs/case-1'
        original = folder / '11 - Notificacion familias.docx'
        original.write_bytes(b'original-11')
        signed = folder / '11 - firmado-director.pdf'
        signed.write_bytes(PDF)
        self.db.execute("""INSERT INTO generated_documents
            (id, case_id, template_name, doc_number, output_path, created_by_user_id)
            VALUES (11, 1, '11 - Notificacion familias.docx', '11', ?, 1)""", (str(original),))
        self.db.execute("""INSERT INTO signature_requests (generated_document_id, signer_name,
            signer_email, signer_role, status, signed_pdf_path)
            VALUES (11, 'Direccion prueba', 'admin@example.test', 'director', 'signed', ?)""", (str(signed),))
        self.db.commit()
        return signed

    def upload(self, data=PDF, filename='familia.pdf', document_id=7, csrf=True):
        fields = {'family_signed_pdf': (io.BytesIO(data), filename)}
        if csrf:
            fields['csrf_token'] = 'test'
        builder = EnvironBuilder(path=f'/documents/{document_id}/family-signed', method='POST', data=fields)
        environment = builder.get_environ()
        try:
            return self.client.open(environment)
        finally:
            environment['wsgi.input'].close()
            builder.close()

    def test_assigned_instructor_upload_download_zip_and_original_preserved(self):
        self.assertEqual(self.upload().status_code, 302)
        row = self.db.execute('SELECT * FROM family_signed_documents').fetchone()
        self.assertEqual(Path(row['output_path']).read_bytes(), PDF)
        self.assertEqual(row['uploaded_by_user_id'], 2)
        self.assertEqual(self.original.read_bytes(), b'original-docx')
        self.assertEqual(self.signed.read_bytes(), PDF)
        self.assertEqual(self.db.execute('SELECT status FROM signature_requests').fetchone()[0], 'signed')
        response = self.client.get(f"/family-signed/{row['id']}/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, PDF)
        response.close()
        archive_response = self.client.get('/cases/1/export')
        with zipfile.ZipFile(io.BytesIO(archive_response.data)) as archive:
            self.assertIn(Path(row['output_path']).name, archive.namelist())
        archive_response.close()

    def test_other_instructor_cannot_upload_or_download(self):
        self.upload()
        self.login(3)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get('/family-signed/1/download').status_code, 403)
        self.assertEqual(self.db.execute('SELECT count(*) FROM family_signed_documents').fetchone()[0], 1)

    def test_csrf_missing_is_rejected(self):
        self.assertEqual(self.upload(csrf=False).status_code, 403)
        self.assertEqual(self.db.execute('SELECT count(*) FROM family_signed_documents').fetchone()[0], 0)

    def test_invalid_files_and_oversized_pdf_are_rejected(self):
        for data, name in [(PDF, 'familia.docx'), (b'not a PDF', 'familia.pdf'),
                           (b'%PDF-1.4\n' + b'x' * (8 * 1024 * 1024) + b'%%EOF', 'large.pdf')]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(data, name).status_code, 302)
        self.assertEqual(self.db.execute('SELECT count(*) FROM family_signed_documents').fetchone()[0], 0)

    def test_request_limit_is_applied_before_form_parsing(self):
        self.assertEqual(self.upload(b'x' * (10 * 1024 * 1024)).status_code, 302)
        self.assertEqual(self.db.execute('SELECT count(*) FROM family_signed_documents').fetchone()[0], 0)

    def test_other_document_types_and_old_versions_are_rejected(self):
        self.db.execute("UPDATE generated_documents SET doc_number='08'")
        self.db.commit()
        self.assertEqual(self.upload().status_code, 400)
        self.db.execute("UPDATE generated_documents SET doc_number='07', is_latest=0")
        self.db.commit()
        self.assertEqual(self.upload().status_code, 400)

    def test_reuploads_preserve_both_copies(self):
        self.upload()
        self.upload(PDF.replace(b'<<>>', b'<</Test 1>>'))
        rows = self.db.execute('SELECT output_path FROM family_signed_documents').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertTrue(all(Path(row[0]).is_file() for row in rows))

    def test_upload_is_rendered_in_case_and_recorded_in_audit(self):
        self.upload()
        with patch('disciplinarios.views.backfill_signature_requests_for_case'):
            response = self.client.get('/cases/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Firma de la familia'.encode(), response.data)
        self.assertIn(b'/family-signed/1/download', response.data)
        self.assertEqual(self.db.execute("SELECT count(*) FROM audit_logs WHERE action='upload_family_signed_pdf'").fetchone()[0], 1)

    def test_upload_after_closure_is_exported_and_detected_by_automatic_sync(self):
        self.upload()
        self.db.execute("UPDATE family_signed_documents SET created_at='2026-11-02 10:00:00'")
        self.db.commit()
        row = self.db.execute('SELECT * FROM family_signed_documents').fetchone()
        source = REMOTE_EXPORT.replace('/home/guardias/expedientes', str(self.root))
        bundle = subprocess.check_output([sys.executable, '-c', source, 'TEST-01'])
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertIn(Path(row['output_path']).name, manifest['files'])
        source = REMOTE_CLOSED_CASES.replace('/home/guardias/expedientes', str(self.root))
        output = subprocess.check_output([sys.executable, '-c', source, '2026-11-01 00:00:00', ''])
        self.assertEqual([c['number'] for c in json.loads(output)['cases']], ['TEST-01'])

    def test_11_accepts_assigned_instructor_upload_without_changing_director_signature(self):
        original_signed = self.add_document_11()
        self.assertEqual(self.upload(document_id=11).status_code, 302)
        row = self.db.execute('SELECT * FROM family_signed_documents').fetchone()
        self.assertEqual(row['generated_document_id'], 11)
        self.assertTrue(Path(row['output_path']).name.startswith('11 - Notificacion familias - firmado-familia'))
        self.assertEqual(original_signed.read_bytes(), PDF)
        signature = self.db.execute('SELECT status, signer_role FROM signature_requests WHERE generated_document_id=11').fetchone()
        self.assertEqual(tuple(signature), ('signed', 'director'))
        response = self.client.get(f"/family-signed/{row['id']}/download")
        self.assertEqual(response.data, PDF)
        response.close()
        with patch('disciplinarios.views.backfill_signature_requests_for_case'):
            response = self.client.get('/cases/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/documents/11/family-signed', response.data)

    def test_11_rejects_other_instructor_and_accepts_admin(self):
        self.add_document_11()
        self.login(3)
        self.assertEqual(self.upload(document_id=11).status_code, 403)
        self.login(1)
        self.assertEqual(self.upload(document_id=11).status_code, 302)
        self.login(3)
        self.assertEqual(self.client.get('/family-signed/1/download').status_code, 403)

    def test_11_previous_version_cannot_receive_upload(self):
        self.add_document_11()
        self.db.execute('UPDATE generated_documents SET is_latest=0 WHERE id=11')
        self.db.commit()
        self.assertEqual(self.upload(document_id=11).status_code, 400)
        self.assertEqual(self.db.execute('SELECT count(*) FROM family_signed_documents').fetchone()[0], 0)

    def test_11_family_pdf_is_in_zip_and_teams_sync_after_closure(self):
        self.add_document_11()
        self.upload(document_id=11)
        self.db.execute("UPDATE family_signed_documents SET created_at='2026-11-02 10:00:00'")
        self.db.commit()
        name = Path(self.db.execute('SELECT output_path FROM family_signed_documents').fetchone()[0]).name
        response = self.client.get('/cases/1/export')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.read(name), PDF)
        response.close()
        source = REMOTE_EXPORT.replace('/home/guardias/expedientes', str(self.root))
        bundle = subprocess.check_output([sys.executable, '-c', source, 'TEST-01'])
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertEqual(archive.read('documents/' + name), PDF)
        source = REMOTE_CLOSED_CASES.replace('/home/guardias/expedientes', str(self.root))
        output = subprocess.check_output([sys.executable, '-c', source, '2026-11-01 00:00:00', ''])
        self.assertEqual([c['number'] for c in json.loads(output)['cases']], ['TEST-01'])


if __name__ == '__main__':
    unittest.main()
