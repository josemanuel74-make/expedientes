import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.sync_teams import synchronize


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


if __name__ == '__main__':
    unittest.main()
