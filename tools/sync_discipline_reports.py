"""Publish the current-course Fenicia reports to the private school app snapshot."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

try:
    from .discipline_excel import read_reports
except ImportError:
    from discipline_excel import read_reports


REMOTE_RECEIVE = r"""
from pathlib import Path
import os, sys, tempfile
from disciplinarios.discipline import load_snapshot
data = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
if len(data) > 25 * 1024 * 1024:
    raise ValueError('Datos demasiado grandes')
folder = Path('/home/guardias/expedientes/instance')
temporary = None
try:
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    snapshot = load_snapshot(temporary)
    temporary.replace(folder / 'discipline_reports.json')
    print('Partes publicados:', len(snapshot['reports']))
finally:
    if temporary is not None:
        temporary.unlink(missing_ok=True)
"""


def run(args):
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with args.state.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Ya hay una sincronizacion de partes en curso.', flush=True)
            return
        before = args.excel.stat()
        if before.st_size > 25 * 1024 * 1024:
            raise ValueError('El Excel supera el tamaño permitido.')
        try:
            data = args.excel.read_bytes()
        except OSError:
            helper = os.environ.get('TEAMS_FILE_HASH_HELPER')
            if not helper:
                raise
            subprocess.run([helper, str(args.excel)], stdout=subprocess.DEVNULL, check=True, timeout=90)
            data = args.excel.read_bytes()
        after = args.excel.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('El Excel se esta actualizando; se reintentara.')
        digest = hashlib.sha256(data).hexdigest()
        previous = json.loads(args.state.read_text()) if args.state.exists() else {}
        if not args.force and previous.get('sha256') == digest and previous.get('school_year') == args.school_year:
            print('Partes: sin cambios en el Excel.', flush=True)
            return
        snapshot = read_reports(data, args.school_year, datetime.fromtimestamp(after.st_mtime, timezone.utc).isoformat())
        payload = json.dumps(snapshot, ensure_ascii=False).encode()
        command = 'cd /home/guardias/expedientes && .venv/bin/python -c ' + shlex.quote(REMOTE_RECEIVE)
        result = subprocess.run(['/usr/bin/ssh', '-p', str(args.port), '-i', str(args.identity),
                                 '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                                 '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', args.host, command],
                                input=payload, stdout=subprocess.PIPE, check=True, timeout=120)
        with tempfile.NamedTemporaryFile(mode='w', dir=args.state.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'sha256': digest, 'school_year': args.school_year,
                       'published_at': datetime.now(timezone.utc).isoformat(), 'records': len(snapshot['reports'])}, stream)
        temporary.replace(args.state)
        print(result.stdout.decode().strip(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--excel', type=Path, required=True)
    parser.add_argument('--school-year', required=True)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--host', default='guardias@rondador.iesleopoldoqueipo.com')
    parser.add_argument('--port', type=int, default=50113)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(f'Sincronizacion de partes pendiente ({type(exc).__name__}); se reintentara.', flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
