"""The warehouse flow, shared by the entry script and the five Airflow tasks.

Each successful load publishes one current staging dataset. Failed runs retain
their .work directory and source fingerprints so loading can be resumed safely.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from etl.extract import audit, cached_payloads, extract, validate_sources
from etl.load import apply_metadata, connect, load, stage_path, validate
from utils.common import atomic_json, checksum, read_json, utcnow, writer_lock

STEPS = ('extract', 'transform', 'load', 'validate', 'olap')


def new_run_id():
    return utcnow().replace(':', '').replace('-', '').replace('.', '') + '-' + uuid.uuid4().hex[:6]


def check_options(cfg, offline, resume_run=None):
    if resume_run and not offline:
        raise ValueError('Resume reuses original staged metadata; use refresh --live after recovery for new metadata')
    if not offline and cfg['synthetic']:
        raise ValueError('Live TMDB is forbidden for synthetic runs')
    if not offline and not os.environ.get('TMDB_TOKEN'):
        raise ValueError('Live extraction requires TMDB_TOKEN')


def reusable_stage(cfg, previous_run):
    if Path(previous_run).name != previous_run or previous_run in ('.', '..'):
        raise ValueError('Invalid resume run identifier')
    root = Path(cfg['paths']['reports'])
    metrics = read_json(root / 'quality' / f'{previous_run}.json', {})
    previous = read_json(root / 'runs' / f'{previous_run}.json', {})
    original_cfg = read_json(Path(cfg['paths']['state']) / f'{previous_run}-config.json', {})
    if not metrics.get('reconciliation') or not previous or not original_cfg:
        raise ValueError('Resume requires a recorded run with reconciled staging')
    for key in ('raw_movielens', 'staging'):
        if original_cfg['paths'][key] != cfg['paths'][key]:
            raise ValueError('Resume source/staging path mismatch')
    fingerprints = metrics.get('source_sha256')
    if fingerprints is None:
        original_audit = read_json(root / 'quality' / 'source_audit.json', {})
        if not previous['started_at'] <= original_audit.get('created_at', '') <= metrics['created_at']:
            raise ValueError('No original pre-staging audit available for resume')
        fingerprints = {name: item['sha256'] for name, item in original_audit['files'].items()
                        if name in ('ratings', 'movies', 'links', 'tags')}
    if set(fingerprints) != {'ratings', 'movies', 'links', 'tags'}:
        raise ValueError('Resume requires all four original source fingerprints')
    for name, digest in fingerprints.items():
        if checksum(Path(cfg['paths']['raw_movielens']) / f'{name}.csv') != digest:
            raise ValueError(f'Resume source fingerprint changed: {name}')
    metrics['source_sha256'] = fingerprints
    journal = read_json(Path(cfg['paths']['state']) / f'{previous_run}-publication.json', {})
    if journal and published_result(cfg, previous_run, metrics) is not None:
        publish_staging(cfg, Path(journal['stage']), metrics, previous_run)
    stage = Path(metrics.get('stage', Path(cfg['paths']['staging']) / previous_run))
    if not all(list(stage_path(stage, name).glob('*.parquet')) for name in fingerprints):
        raise ValueError('Resume staging files are missing')
    # A current dataset may have been replaced by a newer run.
    if stage == Path(cfg['paths']['staging']):
        manifest = read_json(stage / 'manifest.json', {})
        if manifest.get('run_id') != previous_run:
            raise ValueError('Resume staging was replaced by another run')
    return stage, metrics


def publish_staging(cfg, stage, metrics, run_id):
    target = Path(cfg['paths']['staging'])
    if stage != target:
        journal_path = Path(cfg['paths']['state']) / f'{run_id}-publication.json'
        journal = read_json(journal_path, None)
        if journal is None:
            journal = {'stage': str(stage), 'items': [item.name for item in stage.iterdir()]}
            for name in journal['items']:
                (stage / name / '.publication-run').write_text(run_id)
            atomic_json(journal_path, journal)
        previous = target / '.work' / (run_id + '-previous')
        previous.mkdir(parents=True, exist_ok=True)
        for name in journal['items']:
            item, destination = stage / name, target / name
            if item.exists():
                if destination.exists():
                    os.replace(destination, previous / name)
                os.replace(item, destination)
            marker = destination / '.publication-run'
            if not marker.exists() or marker.read_text() != run_id:
                raise ValueError(f'Incomplete staging publication: {name}')
    metrics['stage'] = str(target)
    atomic_json(target / 'manifest.json', {'run_id': run_id, 'source_sha256': metrics['source_sha256']})
    atomic_json(Path(cfg['paths']['reports']) / 'quality' / f'{run_id}.json', metrics)
    if stage != target:
        shutil.rmtree(previous)
        if stage.exists():
            stage.rmdir()


def published_result(cfg, run_id, metrics):
    """A load retry completes staging publication without rewriting committed facts."""
    if not Path(cfg['paths']['warehouse']).exists():
        return None
    with connect(cfg, read_only=True) as con:
        latest = con.execute("SELECT run_id,source_counts FROM ETLRun WHERE mode='full' ORDER BY finished_at DESC LIMIT 1").fetchone()
        if latest is None or latest[0] != run_id:
            return None
        source = json.loads(latest[1])
        if source.get('source_sha256', metrics['source_sha256']) != metrics['source_sha256']:
            raise ValueError('This Airflow run already published different sources; trigger a new run')
        result = validate(con)
        if result['ratings'] != metrics['retained_ratings']:
            raise ValueError('Published rating count differs from recorded staging')
        return result


def execute_stage(cfg, step, run_id, offline=True, tmdb_limit=500, resume_run=None):
    """Execute one persisted stage. The caller holds the pipeline lease."""
    state = Path(cfg['paths']['state'])
    job_path = state / f'{run_id}-job.json'
    report_path = Path(cfg['paths']['reports']) / 'runs' / f'{run_id}.json'
    job = read_json(job_path, {'run_id': run_id, 'started_at': utcnow(), 'synthetic': cfg['synthetic'],
                              'offline': offline, 'mode': 'full', 'completed_steps': []})
    start = time.perf_counter()
    try:
        if step == 'extract':
            check_options(cfg, offline, resume_run)
            validate_sources(cfg)
            atomic_json(state / f'{run_id}-config.json', cfg)
            if resume_run:
                stage, metrics = reusable_stage(cfg, resume_run)
                job.update(stage=str(stage), metrics=metrics, resumed_staging_run=resume_run)
                original_job = read_json(state / f'{resume_run}-job.json', {})
                payloads = original_job.get('payloads', [])
                coverage = {'live': False, 'mode': 'reused_original_staged_metadata'}
            else:
                source = audit(cfg)
                job['source_sha256'] = {name: item['sha256'] for name, item in source['files'].items()
                                        if name in ('ratings', 'movies', 'links', 'tags')}
                payloads, coverage = ((cached_payloads(cfg), {'live': False, 'mode': 'offline_cached'})
                                      if offline else extract(cfg, run_id, tmdb_limit))
            job.update(payloads=payloads, coverage={**coverage, 'enriched_payloads': len(payloads)})
        elif step == 'transform':
            if 'extract' not in job['completed_steps']:
                raise ValueError('Extract must succeed before transform')
            if not job.get('resumed_staging_run'):
                config_path = state / f'{run_id}-config.json'
                try:
                    subprocess.run([sys.executable, '-m', 'etl.transform', str(config_path), run_id], check=True)
                except subprocess.CalledProcessError:
                    rejected = read_json(Path(cfg['paths']['reports']) / 'quality' / f'{run_id}.json', {})
                    if rejected.get('conflicting_events'):
                        raise ValueError(f"{rejected['conflicting_events']} conflicting rating events; staging rejected") from None
                    raise
                metrics = read_json(Path(cfg['paths']['reports']) / 'quality' / f'{run_id}.json')
                stage = Path(cfg['paths']['staging']) / '.work' / run_id
                metrics.update(source_sha256=job['source_sha256'], stage=str(stage))
                atomic_json(Path(cfg['paths']['reports']) / 'quality' / f'{run_id}.json', metrics)
                job.update(stage=str(stage), metrics=metrics)
        elif step == 'load':
            if 'transform' not in job['completed_steps']:
                raise ValueError('Transform must succeed before load')
            # Verify source fingerprints again before loading resumable staging.
            metrics = job['metrics']
            for name, digest in metrics['source_sha256'].items():
                if checksum(Path(cfg['paths']['raw_movielens']) / f'{name}.csv') != digest:
                    raise ValueError(f'Source fingerprint changed: {name}')
            job['warehouse'] = published_result(cfg, run_id, metrics)
            if job['warehouse'] is None:
                job['warehouse'] = load(cfg, Path(job['stage']), metrics, job['payloads'], run_id)
            publish_staging(cfg, Path(job['stage']), metrics, run_id)
            job['stage'] = cfg['paths']['staging']
            job['metrics'] = metrics
            if not offline:
                atomic_json(state / 'tmdb_watermark.json', {'run_id': run_id, 'successful_at': utcnow(),
                            'policy': 'bounded stale refresh; no global change-feed completeness claim'})
        elif step == 'validate':
            with connect(cfg, read_only=True) as con:
                job['warehouse'] = validate(con)
        elif step == 'olap':
            from analytics import benchmark, eda
            options = {'start_year': 2001, 'end_year': 2002, 'min_support': 5} if cfg['synthetic'] else {}
            benchmark(cfg, **options)
            eda(cfg)
        else:
            raise ValueError(f'Unknown pipeline step: {step}')
        job['completed_steps'] = list(dict.fromkeys(job['completed_steps'] + [step]))
        job.setdefault('timings_seconds', {})[step] = time.perf_counter() - start
        job.update(status='success' if step in ('validate', 'olap') else 'in_progress', finished_at=utcnow())
        atomic_json(job_path, job)
        record = {key: value for key, value in job.items() if key not in ('payloads', 'metrics')}
        atomic_json(report_path, record)
        if step == 'olap':
            summary = {'run': record, 'quality': job.get('metrics'),
                       'olap': read_json(Path(cfg['paths']['reports']) / 'results/olap.json')}
            atomic_json(Path(cfg['paths']['reports']) / 'results/warehouse.json', summary)
        return record
    except BaseException as error:
        atomic_json(report_path, {key: value for key, value in job.items() if key not in ('payloads', 'metrics')}
                    | {'status': 'failed', 'failed_step': step, 'error_type': type(error).__name__})
        raise


def run(cfg, mode='full', offline=True, tmdb_limit=500, resume_run=None, analytics=False):
    check_options(cfg, offline, resume_run)
    with writer_lock(Path(cfg['paths']['state']) / 'pipeline'):
        if mode == 'incremental':
            if resume_run:
                raise ValueError('Staging resume is only supported for full loads')
            return refresh(cfg, offline, tmdb_limit)
        run_id = new_run_id()
        result = None
        for step in STEPS if analytics else STEPS[:4]:
            result = execute_stage(cfg, step, run_id, offline, tmdb_limit, resume_run)
        return result


def refresh(cfg, offline=True, tmdb_limit=500):
    run_id = new_run_id()
    payloads, coverage = ((cached_payloads(cfg), {'live': False, 'mode': 'offline_cached'})
                         if offline else extract(cfg, run_id, tmdb_limit, incremental=True))
    with writer_lock(cfg['paths']['warehouse']), connect(cfg) as con:
        con.execute('BEGIN')
        before = con.execute('SELECT count(*) FROM FactRatings').fetchone()[0]
        apply_metadata(con, payloads)
        result = validate(con)
        if result['ratings'] != before:
            raise ValueError('Metadata refresh altered facts')
        con.execute('INSERT INTO ETLRun VALUES (?,?,?,?,?,?,?)',
                    [run_id, 'incremental', utcnow(), utcnow(), 'success', json.dumps(coverage), json.dumps(result)])
        con.execute('COMMIT')
    record = {'run_id': run_id, 'mode': 'incremental', 'status': 'success', 'synthetic': cfg['synthetic'],
              'offline': offline, 'warehouse': result, 'coverage': coverage, 'finished_at': utcnow()}
    atomic_json(Path(cfg['paths']['reports']) / 'runs' / f'{run_id}.json', record)
    if not offline:
        atomic_json(Path(cfg['paths']['state']) / 'tmdb_watermark.json', {'run_id': run_id, 'successful_at': utcnow()})
    return record
