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
        self.bundle = self.make_bundle(self.data)

    @staticmethod
    def make_bundle(data):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'case_number': '03', 'files': {
                'signed.pdf': hashlib.sha256(data).hexdigest()}}))
            archive.writestr('documents/signed.pdf', data)
        return buffer.getvalue()

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

    def test_managed_file_is_updated_when_source_changes(self):
        synchronize(self.bundle, self.root, '03')
        known = {'signed.pdf': hashlib.sha256(self.data).hexdigest()}
        newer = self.make_bundle(b'%PDF-updated')
        self.assertEqual(synchronize(newer, self.root, '03', known_files=known), (1, 0))
        self.assertEqual((self.folder / 'signed.pdf').read_bytes(), b'%PDF-updated')
        self.assertEqual([path.name for path in self.folder.iterdir()], ['signed.pdf'])

    def test_manual_edit_is_not_overwritten_by_managed_update(self):
        synchronize(self.bundle, self.root, '03')
        known = {'signed.pdf': hashlib.sha256(self.data).hexdigest()}
        target = self.folder / 'signed.pdf'
        target.write_bytes(b'manually-edited')
        with self.assertRaises(ValueError):
            synchronize(self.make_bundle(b'%PDF-updated'), self.root, '03', known_files=known)
        self.assertEqual(target.read_bytes(), b'manually-edited')

    def test_preserve_mode_archives_different_copy_before_updating(self):
        target = self.folder / 'signed.pdf'
        target.write_bytes(b'manually-edited')
        self.assertEqual(synchronize(self.bundle, self.root, '03', preserve_previous=True), (1, 0))
        self.assertEqual(target.read_bytes(), self.data)
        backups = list((self.folder / 'Historial de sincronizacion').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'manually-edited')
        self.assertEqual(synchronize(self.bundle, self.root, '03', preserve_previous=True), (0, 1))
        self.assertEqual(len(list(backups[0].parent.iterdir())), 1)

    def test_preserve_dry_run_does_not_archive_or_update(self):
        target = self.folder / 'signed.pdf'
        target.write_bytes(b'previous')
        self.assertEqual(synchronize(self.bundle, self.root, '03', True, preserve_previous=True), (1, 0))
        self.assertEqual(target.read_bytes(), b'previous')
        self.assertFalse((self.folder / 'Historial de sincronizacion').exists())

    def test_failed_preservation_leaves_original_intact(self):
        target = self.folder / 'signed.pdf'
        target.write_bytes(b'previous')
        with patch('tools.sync_teams.preserve_previous_copy', side_effect=OSError('History unavailable')), self.assertRaises(OSError):
            synchronize(self.bundle, self.root, '03', preserve_previous=True)
        self.assertEqual(target.read_bytes(), b'previous')

    def test_managed_dry_run_does_not_replace(self):
        synchronize(self.bundle, self.root, '03')
        known = {'signed.pdf': hashlib.sha256(self.data).hexdigest()}
        self.assertEqual(synchronize(self.make_bundle(b'%PDF-updated'), self.root, '03', True, known), (1, 0))
        self.assertEqual((self.folder / 'signed.pdf').read_bytes(), self.data)

    def test_retry_recognizes_an_update_already_written(self):
        synchronize(self.bundle, self.root, '03')
        older = {'signed.pdf': hashlib.sha256(b'previous-copy').hexdigest()}
        self.assertEqual(synchronize(self.bundle, self.root, '03', known_files=older), (0, 1))

    def test_edit_during_update_is_preserved_and_temporary_file_removed(self):
        synchronize(self.bundle, self.root, '03')
        known = {'signed.pdf': hashlib.sha256(self.data).hexdigest()}
        target = self.folder / 'signed.pdf'
        reads = 0
        def digest(path):
            nonlocal reads
            if path.resolve() == target.resolve():
                reads += 1
                if reads == 2:
                    target.write_bytes(b'edited-during-copy')
            return file_digest(path)
        with patch('tools.sync_teams.file_digest', side_effect=digest), self.assertRaises(ValueError):
            synchronize(self.make_bundle(b'%PDF-updated'), self.root, '03', known_files=known)
        self.assertEqual(target.read_bytes(), b'edited-during-copy')
        self.assertEqual([path.name for path in self.folder.iterdir()], ['signed.pdf'])

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
