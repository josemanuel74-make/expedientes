"""One-shot worker, run by launchd, for closed cases awaiting their Teams copy."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import subprocess

try:
    from .sync_teams import download_bundle, remote_python, synchronize
except ImportError:
    from sync_teams import download_bundle, remote_python, synchronize


REMOTE_CLOSED_CASES = r"""
import hashlib, json, sqlite3, sys
db = sqlite3.connect('file:/home/guardias/expedientes/instance/disciplinarios.sqlite3?mode=ro', uri=True)
db.row_factory = sqlite3.Row
timestamp = db.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]
if sys.argv[2]:
    cases = db.execute("SELECT id, case_number, closed_at FROM cases WHERE status='cerrado' AND case_number=?", (sys.argv[2],)).fetchall()
else:
    cases = db.execute('''SELECT id, case_number, closed_at FROM cases
        WHERE status='cerrado' AND (datetime(closed_at)>=datetime(?) OR EXISTS (
            SELECT 1 FROM family_signed_documents f
            JOIN generated_documents d ON d.id=f.generated_document_id
            WHERE d.case_id=cases.id AND datetime(f.created_at)>=datetime(?)
        )) ORDER BY closed_at, id''', (sys.argv[1], sys.argv[1])).fetchall()
result = []
for case in cases:
    documents = db.execute('''SELECT d.id, d.output_path, d.version_number,
        s.status, s.signed_pdf_path, s.completed_at
        FROM generated_documents d LEFT JOIN signature_requests s ON s.generated_document_id=d.id
        WHERE d.case_id=? AND d.is_latest=1 ORDER BY d.id''', (case['id'],)).fetchall()
    family = db.execute('''SELECT f.id, f.output_path, f.sha256, f.created_at
        FROM family_signed_documents f JOIN generated_documents d ON d.id=f.generated_document_id
        WHERE d.case_id=? ORDER BY f.id''', (case['id'],)).fetchall()
    snapshot = [dict(case), [dict(d) for d in documents], [dict(f) for f in family]]
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    result.append({'number': case['case_number'], 'fingerprint': fingerprint})
print(json.dumps({'timestamp': timestamp, 'cases': result}))
"""


def save_state(path: Path, state: dict):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(state, temporary, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def process_cases(state, cases, fetch, copy, persist):
    failures = 0
    for case in cases:
        number = case['number']
        if state['completed'].get(number, {}).get('fingerprint') == case['fingerprint']:
            continue
        try:
            copied, unchanged = copy(fetch(number), number)
        except Exception as exc:
            failures += 1
            detail = type(exc).__name__ if isinstance(exc, subprocess.SubprocessError) else str(exc)
            state['errors'][number] = {'at': datetime.now(timezone.utc).isoformat(), 'error': detail}
            print(f'Expediente {number}: pendiente; se reintentara. {detail}', flush=True)
        else:
            state['completed'][number] = {
                'fingerprint': case['fingerprint'],
                'copied_to_onedrive_at': datetime.now(timezone.utc).isoformat(),
                'copied': copied, 'unchanged': unchanged,
            }
            state['errors'].pop(number, None)
            print(f'Expediente {number}: {copied} archivos copiados, {unchanged} identicos; verificados. OneDrive completa la subida.', flush=True)
        persist(state)
    return failures


def run(args):
    state_path = args.state.expanduser().resolve()
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state_path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Ya hay una copia en curso.', flush=True)
            return 0
        state = json.loads(state_path.read_text()) if state_path.exists() else None
        if args.initialize and state is not None:
            print('Se conserva el estado y los reintentos existentes.', flush=True)
            return 0
        if state is None and not args.initialize:
            raise ValueError('Inicializa el estado antes de activar la tarea.')
        response = json.loads(remote_python(
            REMOTE_CLOSED_CASES, [state['since'] if state else '9999-01-01', args.case_number or ''],
            args.identity, args.host, args.port,
        ))
        if args.initialize:
            state = {'since': response['timestamp'], 'completed': {}, 'errors': {}}
            save_state(state_path, state)
            print('Activado para cierres desde ' + state['since'] + ' UTC.', flush=True)
            return 0
        if args.case_number and not response['cases']:
            raise ValueError('El expediente solicitado no existe o no esta cerrado.')
        failures = process_cases(
            state, response['cases'],
            lambda number: download_bundle(number, args.identity, args.host, args.port),
            lambda bundle, number: synchronize(bundle, args.teams_root, number),
            lambda value: save_state(state_path, value),
        )
        state['last_scan_at'] = response['timestamp']
        save_state(state_path, state)
        print(f"Revision {response['timestamp']} UTC: {len(response['cases'])} cierres, {failures} pendientes.", flush=True)
        return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teams-root', required=True, type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--host', default='guardias@rondador.iesleopoldoqueipo.com')
    parser.add_argument('--port', type=int, default=50113)
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--case', dest='case_number')
    try:
        result = run(parser.parse_args())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Avoid dumping the SSH command and embedded query into recurring logs.
        print(f'Revision pendiente ({type(exc).__name__}); se reintentara en la siguiente ejecucion.', flush=True)
        result = 1
    raise SystemExit(result)


if __name__ == '__main__':
    main()
