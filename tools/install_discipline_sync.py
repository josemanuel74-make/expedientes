"""Install the read-only Fenicia report mirror for the school app."""

import argparse
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--excel', type=Path, required=True)
    parser.add_argument('--school-year', required=True)
    parser.add_argument('--identity', type=Path, required=True)
    args = parser.parse_args()
    if importlib.util.find_spec('openpyxl') is None:
        raise RuntimeError('Instala tools/requirements-discipline-sync.txt en este interprete de Python.')
    excel = args.excel.expanduser().resolve(strict=True)
    identity = args.identity.expanduser().resolve(strict=True)
    source = Path(__file__).resolve().parent
    support = Path.home() / 'Library/Application Support/ExpedientesTeamsSync'
    runtime = support / 'discipline-runtime'
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('sync_discipline_reports.py', 'discipline_excel.py'):
        data = (source / name).read_bytes()
        compile(data, name, 'exec')
        with tempfile.NamedTemporaryFile(dir=runtime, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(runtime / name)
    command = [str(Path(sys.executable).resolve()), str(runtime / 'sync_discipline_reports.py'),
               '--excel', str(excel), '--school-year', args.school_year,
               '--identity', str(identity), '--state', str(support / 'discipline-state.json')]
    environment = {'PYTHONUNBUFFERED': '1'}
    helper = support / 'coordinated-sha256'
    if helper.is_file():
        environment['TEAMS_FILE_HASH_HELPER'] = str(helper)
    subprocess.run(command + ['--force'], check=True, env={**os.environ, **environment}, timeout=240)
    label = 'es.edumelilla.expedientes-discipline-reports'
    domain = f'gui/{os.getuid()}'
    service = domain + '/' + label
    path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {'Label': label, 'ProgramArguments': command, 'WorkingDirectory': str(runtime),
              'RunAtLoad': True, 'StartInterval': 300, 'ProcessType': 'Background',
              'EnvironmentVariables': environment, 'StandardOutPath': str(support / 'discipline.log'),
              'StandardErrorPath': str(support / 'discipline-error.log')}
    if subprocess.run(['/bin/launchctl', 'print', service], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.run(['/bin/launchctl', 'bootout', service], check=True)
    with path.open('wb') as stream:
        plistlib.dump(config, stream)
    path.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], check=True)
    print('Partes conectados a la app; revision automatica cada 5 minutos.')


if __name__ == '__main__':
    main()
