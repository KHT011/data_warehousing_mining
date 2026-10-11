"""Startup hygiene for the single Airflow standalone Compose service."""
from pathlib import Path
import os
import sys


def cleanup_airflow_runtime(home):
    # AIRFLOW_HOME survives containers; PID identities do not. Run only before
    # starting the single standalone service, never before ordinary Airflow CLI use.
    for name in ('airflow-webserver.pid','airflow-webserver-monitor.pid'):
        (Path(home)/name).unlink(missing_ok=True)


if __name__ == '__main__':
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
