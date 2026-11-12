"""Copy a case's latest documents from the VPS to an existing OneDrive/Teams folder."""

import argparse
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import zipfile


REMOTE_EXPORT = r"""
import hashlib, io, json, sqlite3, sys, zipfile
from pathlib import Path
root = Path('/home/guardias/expedientes')
db = sqlite3.connect('file:' + str(root / 'instance/disciplinarios.sqlite3') + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
case = db.execute('SELECT id, case_number FROM cases WHERE case_number = ?', (sys.argv[1],)).fetchone()
if case is None:
    raise RuntimeError('Expediente no encontrado')
rows = db.execute('''SELECT d.output_path, s.signed_pdf_path
    FROM generated_documents d
    LEFT JOIN signature_requests s ON s.generated_document_id = d.id
    WHERE d.case_id = ? AND d.is_latest = 1 ORDER BY d.id''', (case['id'],)).fetchall()
rows += db.execute('''SELECT f.output_path, NULL AS signed_pdf_path
    FROM family_signed_documents f JOIN generated_documents d ON d.id=f.generated_document_id
    WHERE d.case_id=? ORDER BY f.id''', (case['id'],)).fetchall()
files = {}
for row in rows:
    for key in ('output_path', 'signed_pdf_path'):
        if not row[key]:
            continue
        path = Path(row[key]).resolve()
        if not path.is_relative_to((root / 'generated_docs').resolve()):
            raise RuntimeError('Ruta de documento fuera del almacenamiento')
        if path.name in files:
            raise RuntimeError('Nombres de documento duplicados')
        files[path.name] = path.read_bytes()
if not files:
    raise RuntimeError('El expediente no tiene documentos')
manifest = {'case_number': case['case_number'], 'files': {
    name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('manifest.json', json.dumps(manifest))
    for name, data in files.items():
        archive.writestr('documents/' + name, data)
sys.stdout.buffer.write(buffer.getvalue())
"""


def file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        helper = os.environ.get('TEAMS_FILE_HASH_HELPER', '')
        if exc.errno not in {errno.EDEADLK, errno.ETIMEDOUT, errno.EAGAIN} or not helper:
            raise
        result = subprocess.check_output([helper, str(path)], timeout=90).decode().strip()
        if len(result) != 64 or any(c not in '0123456789abcdef' for c in result):
            raise ValueError('Resultado de integridad no valido.')
        return result


def preserve_previous_copy(target: Path, expected_hash: str):
    history = target.parent / 'Historial de sincronizacion'
    if history.is_symlink():
        raise ValueError('El historial no puede ser un enlace simbolico.')
    history.mkdir(exist_ok=True)
    backup = history / f'{target.stem} - copia anterior {expected_hash[:16]}{target.suffix}'
    if backup.is_symlink() or target.is_symlink():
        raise ValueError('El archivo no puede ser un enlace simbolico.')
    if not backup.exists():
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError('El archivo ha cambiado antes de conservar su copia: ' + target.name)
        created = False
        try:
            with backup.open('xb') as stream:
                created = True
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            if created:
                backup.unlink(missing_ok=True)
            raise
    if file_digest(backup) != expected_hash:
        raise ValueError('La copia anterior no supera la comprobacion de integridad.')


def synchronize(bundle: bytes, teams_root: Path, case_number: str, dry_run: bool = False,
                known_files: dict[str, str] | None = None, preserve_previous: bool = False):
    teams_root = teams_root.expanduser().resolve(strict=True)
    folders = [p for p in teams_root.iterdir() if p.is_dir() and p.name.startswith(case_number + ' - ')]
    if len(folders) != 1 or folders[0].is_symlink():
        raise ValueError('Debe existir una unica carpeta de Teams con el prefijo del expediente.')
    destination = folders[0]
    pending = []
    unchanged = 0
    known_files = known_files or {}
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest['case_number'] != case_number or not manifest['files']:
            raise ValueError('El paquete no corresponde al expediente solicitado.')
        # Validate every file before modifying the destination.
        for name, expected_hash in manifest['files'].items():
            if Path(name).name != name or name in {'.', '..'}:
                raise ValueError('Nombre de archivo no valido.')
            data = archive.read('documents/' + name)
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise ValueError('La comprobacion de integridad ha fallado.')
            target = destination / name
            if target.is_symlink():
                raise ValueError('El destino contiene un enlace simbolico.')
            if target.exists():
                previous_hash = file_digest(target)
                if previous_hash == expected_hash:
                    unchanged += 1
                elif preserve_previous or known_files.get(name) == previous_hash:
                    pending.append((target, data, expected_hash, previous_hash))
                else:
                    raise ValueError('Ya existe un archivo diferente: ' + name)
            else:
                pending.append((target, data, expected_hash, None))
    if not dry_run:
        for target, data, expected_hash, previous_hash in pending:
            if previous_hash is None:
                # Exclusive creation prevents overwriting a file added during the copy.
                created = False
                try:
                    with target.open('xb') as stream:
                        created = True
                        stream.write(data)
                except Exception:
                    if created:
                        target.unlink(missing_ok=True)
                    raise
            else:
                if preserve_previous:
                    preserve_previous_copy(target, previous_hash)
                temporary_path = None
                try:
                    with tempfile.NamedTemporaryFile(dir=destination, prefix='.expedientes-sync-', suffix='.tmp', delete=False) as stream:
                        temporary_path = Path(stream.name)
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if file_digest(temporary_path) != expected_hash:
                        raise ValueError('La comprobacion del archivo actualizado ha fallado.')
                    if target.is_symlink() or file_digest(target) != previous_hash:
                        raise ValueError('El archivo ha cambiado durante la copia: ' + target.name)
                    temporary_path.replace(target)
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
            if file_digest(target) != expected_hash:
                raise ValueError('La verificacion del archivo copiado ha fallado.')
    return len(pending), unchanged


def download_bundle(case_number: str, identity: Path, host: str, port: int) -> bytes:
    return remote_python(REMOTE_EXPORT, [case_number], identity, host, port)


def remote_python(source: str, arguments: list[str], identity: Path, host: str, port: int) -> bytes:
    command = '.venv/bin/python -c ' + shlex.quote(source)
    command += ''.join(' ' + shlex.quote(value) for value in arguments)
    result = subprocess.run(
        ['/usr/bin/ssh', '-p', str(port), '-i', str(identity.expanduser()),
         '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
         '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', host,
         'cd /home/guardias/expedientes && ' + command],
        stdout=subprocess.PIPE, check=True, timeout=120,
    )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, dest='case_number')
    parser.add_argument('--teams-root', required=True, type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--host', default='guardias@rondador.iesleopoldoqueipo.com')
    parser.add_argument('--port', type=int, default=50113)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    bundle = download_bundle(args.case_number, args.identity, args.host, args.port)
    copied, unchanged = synchronize(bundle, args.teams_root, args.case_number, args.dry_run)
    print(f'Expediente {args.case_number}: {copied} archivos ' +
          ('pendientes de copiar' if args.dry_run else 'copiados y verificados') +
          f', {unchanged} identicos. OneDrive debe completar la subida a Teams.')


if __name__ == '__main__':
    main()
