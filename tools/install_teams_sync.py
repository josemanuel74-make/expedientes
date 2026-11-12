"""Install the macOS background worker using the existing SSH and OneDrive setup."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


LABEL = 'es.edumelilla.expedientes-teams-sync'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teams-root', required=True, type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    args = parser.parse_args()
    teams_root = args.teams_root.expanduser().resolve(strict=True)
    identity = args.identity.expanduser().resolve(strict=True)
    project_root = Path(__file__).resolve().parent.parent
    support = Path.home() / 'Library/Application Support/ExpedientesTeamsSync'
    support.mkdir(mode=0o700, parents=True, exist_ok=True)
    support.chmod(0o700)
    # Background ssh cannot read keys kept in macOS's protected Downloads folder.
    # Keep the existing identity private to this user, without changing VPS access.
    installed_identity = support / 'id_ed25519'
    if identity != installed_identity:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=support, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(identity.read_bytes())
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(installed_identity)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    installed_identity.chmod(0o600)
    hash_helper = support / 'coordinated-sha256'
    subprocess.run(['/usr/bin/xcrun', 'swiftc',
                    str(project_root / 'tools/coordinated_sha256.swift'),
                    '-o', str(hash_helper)], check=True, timeout=120)
    hash_helper.chmod(0o700)
    runtime = support / 'runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    for name in ('auto_sync_teams.py', 'sync_teams.py'):
        data = (project_root / 'tools' / name).read_bytes()
        compile(data, name, 'exec')
        with tempfile.NamedTemporaryFile(dir=runtime, delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
        temporary_path.replace(runtime / name)
    command = [str(Path(sys.executable).resolve()), str(runtime / 'auto_sync_teams.py'),
               '--teams-root', str(teams_root), '--identity', str(installed_identity),
               '--state', str(support / 'state.json')]
    subprocess.run(command + ['--initialize'], check=True, timeout=150)
    domain = f'gui/{os.getuid()}'
    service = domain + '/' + LABEL
    launch_agents = Path.home() / 'Library/LaunchAgents'
    launch_agents.mkdir(parents=True, exist_ok=True)
    path = launch_agents / (LABEL + '.plist')
    configuration = {
        'Label': LABEL, 'ProgramArguments': command,
        'WorkingDirectory': str(runtime),
        'RunAtLoad': True, 'StartInterval': 300,
        'ProcessType': 'Background', 'LowPriorityIO': True,
        'EnvironmentVariables': {'PYTHONUNBUFFERED': '1', 'TEAMS_FILE_HASH_HELPER': str(hash_helper)},
        'StandardOutPath': str(support / 'worker.log'),
        'StandardErrorPath': str(support / 'worker-error.log'),
    }
    if subprocess.run(['/bin/launchctl', 'print', service], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.run(['/bin/launchctl', 'bootout', service], check=True)
    with path.open('wb') as stream:
        plistlib.dump(configuration, stream)
    path.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], check=True)
    print(f'Tarea activada: {LABEL}; revision cada 5 minutos y al iniciar sesion.')


if __name__ == '__main__':
    main()
