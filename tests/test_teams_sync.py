import hashlib
import errno
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.sync_teams import file_digest, synchronize


class TeamsCopyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.folder = self.root / '03 - Test'
        self.folder.mkdir()
        self.data = b'%PDF-test'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'case_number': '03', 'files': {
                'signed.pdf': hashlib.sha256(self.data).hexdigest()}}))
            archive.writestr('documents/signed.pdf', self.data)
        self.bundle = buffer.getvalue()

    def test_copy_is_verified_and_repeat_is_unchanged(self):
        self.assertEqual(synchronize(self.bundle, self.root, '03'), (1, 0))
        self.assertEqual((self.folder / 'signed.pdf').read_bytes(), self.data)
        self.assertEqual(synchronize(self.bundle, self.root, '03'), (0, 1))

    def test_dry_run_does_not_write(self):
        self.assertEqual(synchronize(self.bundle, self.root, '03', True), (1, 0))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_conflict_does_not_overwrite(self):
        target = self.folder / 'signed.pdf'
        target.write_bytes(b'existing')
        with self.assertRaises(ValueError):
            synchronize(self.bundle, self.root, '03')
        self.assertEqual(target.read_bytes(), b'existing')

    def test_ambiguous_folder_is_rejected(self):
        (self.root / '03 - Other').mkdir()
        with self.assertRaises(ValueError):
            synchronize(self.bundle, self.root, '03')

    def test_wrong_case_is_rejected(self):
        (self.root / '04 - Other').mkdir()
        with self.assertRaises(ValueError):
            synchronize(self.bundle, self.root, '04')

    def test_cloud_placeholder_uses_coordinated_reader(self):
        digest = hashlib.sha256(self.data).hexdigest()
        with patch.object(Path, 'read_bytes', side_effect=OSError(errno.EDEADLK, 'Placeholder')), \
             patch.dict('os.environ', {'TEAMS_FILE_HASH_HELPER': '/private/helper'}), \
             patch('tools.sync_teams.subprocess.check_output', return_value=(digest + '\n').encode()) as read:
            self.assertEqual(file_digest(self.folder / 'signed.pdf'), digest)
            read.assert_called_once()

    def test_unrelated_read_failure_is_not_hidden(self):
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('Denied')), \
             self.assertRaises(PermissionError):
            file_digest(self.folder / 'signed.pdf')


if __name__ == '__main__':
    unittest.main()
