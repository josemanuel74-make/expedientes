from argparse import Namespace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.auto_sync_teams import REMOTE_CLOSED_CASES, process_cases, run


class PendingCaseTests(unittest.TestCase):
    def setUp(self):
        self.state = {'since': '2026-10-27 10:00:00', 'completed': {}, 'errors': {}}
        self.cases = [{'number': '04', 'fingerprint': 'first'}]
        self.fetch = Mock(return_value=b'archive')
        self.copy = Mock(return_value=(26, 0))
        self.persist = Mock()

    def process(self):
        return process_cases(self.state, self.cases, self.fetch, self.copy, self.persist)

    def test_completed_case_is_copied_once(self):
        self.assertEqual(self.process(), 0)
        self.assertEqual(self.process(), 0)
        self.copy.assert_called_once_with(b'archive', '04')
        self.assertEqual(self.state['completed']['04']['fingerprint'], 'first')

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
        self.fetch.side_effect = [OSError('Network error'), b'archive']
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


class ClosedCaseQueryTests(unittest.TestCase):
    def test_only_newly_closed_cases_are_selected_and_changes_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'cases.sqlite3'
            db = sqlite3.connect(database)
            db.executescript(Path('disciplinarios/schema.sql').read_text())
            db.execute("INSERT INTO students (id, full_name, course_name, group_name, guardians_name) VALUES (1, 'Test', 'Test', 'Test', 'Test')")
            for number, status, closed_at in [('01', 'cerrado', '2026-10-26 00:00:00'),
                                               ('02', 'iniciado', None),
                                               ('03', 'cerrado', '2026-10-27 10:00:00')]:
                db.execute("INSERT INTO cases (case_number, student_id, status, fact_known_date, facts_summary, closed_at) VALUES (?, 1, ?, '2026-10-01', 'Test', ?)",
                           (number, status, closed_at))
            db.commit()
            source = REMOTE_CLOSED_CASES.replace('/home/guardias/expedientes/instance/disciplinarios.sqlite3', str(database))
            def query():
                output = subprocess.check_output([sys.executable, '-c', source, '2026-10-27 00:00:00', ''])
                return json.loads(output)['cases']
            before = query()
            self.assertEqual([row['number'] for row in before], ['03'])
            db.execute("INSERT INTO generated_documents (case_id, template_name, output_path) VALUES (3, 'Test', '/test.docx')")
            db.commit()
            after = query()
            self.assertNotEqual(before[0]['fingerprint'], after[0]['fingerprint'])
            db.close()


if __name__ == '__main__':
    unittest.main()
