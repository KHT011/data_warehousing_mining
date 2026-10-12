"""Prepare local MovieLens data and start the requested container service."""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import zipfile


MOVIELENS_FILES = (
    'ratings.csv', 'movies.csv', 'tags.csv', 'links.csv',
    'genome-scores.csv', 'genome-tags.csv',
)


def prepare_raw_data(archive, raw):
    """Flatten the official archive, preserving files already present in raw."""
    archive, raw = Path(archive), Path(raw)
    if all((raw / name).is_file() for name in MOVIELENS_FILES):
        return
    if not archive.is_file():
        print('MovieLens ZIP absent; place ml-20m.zip in the project folder '
              'and restart to prepare full data. Synthetic smoke is available.', flush=True)
        return
    # Both Compose services may start together. Linux flock releases on exit,
    # including interrupted extraction; partial files never become raw CSVs.
    import fcntl
    raw.mkdir(parents=True, exist_ok=True)
    with (raw / '.extract.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        missing = [name for name in MOVIELENS_FILES if not (raw / name).is_file()]
        if not missing:
            return
        with zipfile.ZipFile(archive) as zipped:
            members = {name: 'ml-20m/' + name for name in missing}
            absent = [name for name, member in members.items() if member not in zipped.namelist()]
            if absent:
                raise ValueError(f'MovieLens archive missing CSVs: {absent}')
            with tempfile.TemporaryDirectory(prefix='.extract-', dir=raw) as temporary:
                for name, member in members.items():
                    target = Path(temporary) / name
                    print(f'Extracting {name} to {raw}', flush=True)
                    with zipped.open(member) as source, target.open('wb') as destination:
                        shutil.copyfileobj(source, destination)
                    target.replace(raw / name)


def cleanup_airflow_runtime(home):
    # AIRFLOW_HOME survives containers; PID identities do not. Run only before
    # starting the single standalone service, never before ordinary Airflow CLI use.
    for name in ('airflow-webserver.pid','airflow-webserver-monitor.pid'):
        (Path(home)/name).unlink(missing_ok=True)


if __name__ == '__main__':
    prepare_raw_data('/input/ml-20m.zip', '/app/data/raw')
    args = sys.argv[1:] or ['idle']
    if args[0] == 'idle':
        os.execvp('sleep', ['sleep', 'infinity'])
    elif args[0] == 'airflow':
        if args[1:] == ['standalone']:
            cleanup_airflow_runtime(os.environ.get('AIRFLOW_HOME', '/opt/airflow'))
        os.execv('/opt/airflow-venv/bin/airflow', ['airflow', *args[1:]])
    elif args[0] in ('bash', 'sh', 'python', 'python3'):
        os.execvp(args[0], args)
    else:
        os.execv(sys.executable, [sys.executable, '/app/run_pipeline.py', *args])
