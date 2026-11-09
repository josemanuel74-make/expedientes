from argparse import Namespace
import json
import hashlib
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from tools.auto_sync_teams import REMOTE_CASES, process_cases, run
from tools.sync_teams import REMOTE_EXPORT


class PendingCaseTests(unittest.TestCase):
    def setUp(self):
        self.state = {'since': '2026-10-27 10:00:00', 'completed': {}, 'errors': {}}
        self.cases = [{'number': '04', 'fingerprint': 'first'}]
        buffer = io.BytesIO()
        self.files = {'test.pdf': hashlib.sha256(b'test').hexdigest()}
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'files': self.files}))
        self.bundle = buffer.getvalue()
        self.fetch = Mock(return_value=self.bundle)
        self.copy = Mock(return_value=(26, 0))
        self.persist = Mock()

    def process(self):
        return process_cases(self.state, self.cases, self.fetch, self.copy, self.persist)

    def test_completed_case_is_copied_once(self):
        self.assertEqual(self.process(), 0)
        self.assertEqual(self.process(), 0)
        self.copy.assert_called_once_with(self.bundle, '04')
        self.assertEqual(self.state['completed']['04']['fingerprint'], 'first')
        self.assertEqual(self.state['completed']['04']['files'], self.files)

    def test_failure_is_retained_and_retried(self):
        self.copy.side_effect = [OSError('Carpeta todavia no disponible'), (26, 0)]
        self.assertEqual(self.process(), 1)
        self.assertNotIn('04', self.state['completed'])
        self.assertIn('04', self.state['errors'])
        self.assertEqual(self.process(), 0)
        self.assertNotIn('04', self.state['errors'])

    def test_changed_documents_are_processed_again(self):
        self.process()
        self.cases[0]['fingerprint'] = 'new-signature'
        self.process()
        self.assertEqual(self.copy.call_count, 2)

    def test_one_failure_does_not_block_other_cases(self):
        self.cases.append({'number': '05', 'fingerprint': 'second'})
        self.fetch.side_effect = [OSError('Network error'), self.bundle]
        self.assertEqual(self.process(), 1)
        self.assertNotIn('04', self.state['completed'])
        self.assertIn('05', self.state['completed'])

    def test_initialization_does_not_copy_historical_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(state=Path(directory) / 'state.json', initialize=True,
                             case_number=None, identity=Path('key'), host='test', port=22)
            response = json.dumps({'timestamp': '2026-10-27 10:00:00', 'cases': []}).encode()
            with patch('tools.auto_sync_teams.remote_python', return_value=response), \
                 patch('tools.auto_sync_teams.download_bundle') as download:
                self.assertEqual(run(args), 0)
                download.assert_not_called()
            self.assertEqual(json.loads(args.state.read_text())['since'], '2026-10-27 10:00:00')


class CaseQueryTests(unittest.TestCase):
    def test_open_and_old_closed_cases_are_monitored_and_content_changes_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'instance').mkdir()
            (root / 'generated_docs').mkdir()
            database = root / 'instance/disciplinarios.sqlite3'
            db = sqlite3.connect(database)
            db.executescript(Path('disciplinarios/schema.sql').read_text())
            db.execute("INSERT INTO students (id, full_name, course_name, group_name, guardians_name) VALUES (1, 'Test', 'Test', 'Test', 'Test')")
            for number, status, closed_at in [('01', 'cerrado', '2026-10-26 00:00:00'),
                                               ('02', 'iniciado', None),
                                               ('03', 'cerrado', '2026-10-27 10:00:00')]:
                db.execute("INSERT INTO cases (case_number, student_id, status, fact_known_date, facts_summary, closed_at) VALUES (?, 1, ?, '2026-10-01', 'Test', ?)",
                           (number, status, closed_at))
                case_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
                path = root / 'generated_docs' / f'document-{number}.docx'
                path.write_bytes(b'original')
                db.execute("INSERT INTO generated_documents (case_id, template_name, output_path) VALUES (?, 'Test', ?)", (case_id, str(path)))
            db.commit()
            source = REMOTE_CASES.replace('/home/guardias/expedientes', str(root))
            def query():
                output = subprocess.check_output([sys.executable, '-c', source, '2026-10-27 00:00:00', ''])
                return json.loads(output)['cases']
            before = query()
            self.assertEqual([row['number'] for row in before], ['01', '02', '03'])
            (root / 'generated_docs/document-01.docx').write_bytes(b'changed!')
            after = query()
            self.assertNotEqual(before[0]['fingerprint'], after[0]['fingerprint'])
            self.assertEqual(before[1]['fingerprint'], after[1]['fingerprint'])
            self.assertEqual(before[2]['fingerprint'], after[2]['fingerprint'])
            signed = root / 'generated_docs/signed.pdf'
            signed.write_bytes(b'old-signed-pdf')
            db.execute("""INSERT INTO signature_requests (generated_document_id, signer_name,
                signer_email, signer_role, status, signed_pdf_path)
                VALUES (1, 'Test', 'test@example.test', 'director', 'signed', ?)""", (str(signed),))
            db.commit()
            before_signature_change = query()
            signed.write_bytes(b'new-signed-pdf')
            after_signature_change = query()
            self.assertNotEqual(before_signature_change[0]['fingerprint'], after_signature_change[0]['fingerprint'])
            db.close()


class AutomaticUpdateIntegrationTests(unittest.TestCase):
    def test_same_name_signature_update_then_manual_conflict_in_old_closed_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / 'server'
            (source_root / 'instance').mkdir(parents=True)
            documents = source_root / 'generated_docs'
            documents.mkdir()
            original = documents / 'original.docx'
            original.write_bytes(b'original-docx')
            signed = documents / 'signed.pdf'
            signed.write_bytes(b'%PDF-first-signature')
            database = source_root / 'instance/disciplinarios.sqlite3'
            db = sqlite3.connect(database)
            db.executescript(Path('disciplinarios/schema.sql').read_text())
            db.execute("INSERT INTO students (id, full_name, course_name, group_name, guardians_name) VALUES (1, 'Test', 'Test', 'Test', 'Test')")
            db.execute("""INSERT INTO cases (id, case_number, student_id, status,
                fact_known_date, facts_summary, closed_at)
                VALUES (1, '01', 1, 'cerrado', '2026-01-01', 'Test', '2026-01-02')""")
            db.execute("INSERT INTO generated_documents (id, case_id, template_name, output_path) VALUES (1, 1, 'Test', ?)", (str(original),))
            db.execute("""INSERT INTO signature_requests (generated_document_id, signer_name,
                signer_email, signer_role, status, signed_pdf_path)
                VALUES (1, 'Test', 'test@example.test', 'director', 'signed', ?)""", (str(signed),))
            db.commit()
            db.close()
            teams = root / 'teams'
            target = teams / '01 - Test'
            target.mkdir(parents=True)
            args = Namespace(state=root / 'state.json', initialize=True, case_number=None,
                             identity=Path('key'), host='test', port=22, teams_root=teams)
            def remote(source, arguments, *_):
                source = source.replace('/home/guardias/expedientes', str(source_root))
                return subprocess.check_output([sys.executable, '-c', source, *arguments])
            def fetch(number, *parameters):
                return remote(REMOTE_EXPORT, [number], *parameters)
            with patch('tools.auto_sync_teams.remote_python', side_effect=remote), \
                 patch('tools.auto_sync_teams.download_bundle', side_effect=fetch) as download:
                self.assertEqual(run(args), 0)
                args.initialize = False
                self.assertEqual(run(args), 0)
                signed.write_bytes(b'%PDF-second-signature')
                self.assertEqual(run(args), 0)
                self.assertEqual((target / 'signed.pdf').read_bytes(), b'%PDF-second-signature')
                self.assertEqual(run(args), 0)
                self.assertEqual(download.call_count, 2)
                (target / 'signed.pdf').write_bytes(b'manual-teams-edit')
                signed.write_bytes(b'%PDF-third-signature')
                self.assertEqual(run(args), 1)
                self.assertEqual((target / 'signed.pdf').read_bytes(), b'manual-teams-edit')
                state = json.loads(args.state.read_text())
                self.assertIn('01', state['errors'])
                self.assertEqual(state['completed']['01']['files']['signed.pdf'], hashlib.sha256(b'%PDF-second-signature').hexdigest())


if __name__ == '__main__':
    unittest.main()
