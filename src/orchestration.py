"""Airflow passes only arguments; processing uses the core Python runtime."""
import hashlib
import logging
import os
import subprocess

STEPS = ('extract', 'transform', 'load', 'validate', 'olap')


def build_command(step, params, config_path=None, run_id='manual'):
    if step not in STEPS:
        raise ValueError(f'Unknown pipeline step: {step}')
    smoke, live = params.get('smoke', False), params.get('live', False)
    if not isinstance(smoke, bool) or not isinstance(live, bool):
        raise ValueError('smoke/live parameters must be Boolean')
    if smoke and live:
        raise ValueError('Live TMDB is forbidden for synthetic runs')
    if live and not os.environ.get('TMDB_TOKEN'):
        raise ValueError('Live extraction requires TMDB_TOKEN')
    limit = str(params.get('tmdb_limit', 500))
    if limit != 'all' and (not limit.isdigit() or int(limit) < 1):
        raise ValueError('TMDB limit must be a positive integer or all')
    identifier = 'airflow-' + hashlib.sha256(run_id.encode()).hexdigest()[:20]
    command = ['/usr/local/bin/python', '/app/run_pipeline.py', 'stage', step,
               '--run-id', identifier, '--tmdb-limit', limit]
    if config_path:
        command += ['--config', str(config_path)]
    if smoke:
        command += ['--smoke']
    if live:
        command += ['--live']
    if params.get('resume_run'):
        command += ['--resume-run', str(params['resume_run'])]
    return command


def run_step(step, params, run_id='manual', config_path=None, project_root='/app'):
    command = build_command(step, params, config_path, run_id)
    environment = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONFAULTHANDLER': '1'}
    # Native engine messages go to OS stderr. Forward them through Airflow's
    # logger so the task Logs tab includes the cause, not just CalledProcessError.
    logger = logging.getLogger(__name__)
    with subprocess.Popen(command, cwd=project_root, env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors='replace', bufsize=1) as process:
        try:
            for line in process.stdout:
                logger.info('pipeline | %s', line.rstrip())
            returncode = process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
