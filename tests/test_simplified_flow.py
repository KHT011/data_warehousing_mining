"""Contracts for the smaller warehouse-first workflow."""
from pathlib import Path
import socket
import threading

import pytest


def test_ui_lease_blocks_pipeline_before_extract(cfg):
    from pipeline import run
    from utils.common import writer_lock

    with writer_lock(Path(cfg['paths']['state']) / 'pipeline'):
        with pytest.raises(RuntimeError, match='DuckDB UI|pipeline'):
            run(cfg)
    assert not Path(cfg['paths']['warehouse']).exists()


def test_forwarder_preserves_bytes_and_closes_cleanly():
    from utils.duckdb_ui import forwarding_server

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    def echo():
        with listener:
            peer, _ = listener.accept()
            with peer:
                peer.sendall(peer.recv(4096))
    worker = threading.Thread(target=echo)
    worker.start()
    with forwarding_server('127.0.0.1', 0, listener.getsockname()) as server:
        address = server.server_address
        with socket.create_connection(address, timeout=5) as client:
            request = b'Origin: http://localhost:4213\r\n\r\nhello'
            client.sendall(request)
            assert client.recv(4096) == request
    worker.join(timeout=5)
    with pytest.raises(OSError):
        socket.create_connection(address, timeout=1)


def test_presentation_queries_run_without_python_parameters(cfg):
    from pipeline import run
    from etl.load import connect
    from analytics import read_queries

    run(cfg)
    queries = read_queries()
    assert len(queries) == 5
    with connect(cfg, read_only=True) as con:
        for sql in queries:
            assert '$' not in sql
            con.execute(sql).fetchall()


def test_smoke_never_calls_live_api(cfg, monkeypatch):
    from pipeline import run
    monkeypatch.setenv('TMDB_TOKEN', 'private-test-token')
    with pytest.raises(ValueError, match='synthetic'):
        run(cfg, offline=False)


@pytest.mark.parametrize('interruption', ['move', 'manifest'])
def test_interrupted_staging_publication_can_resume(tmp_path, monkeypatch, interruption):
    import pipeline
    from utils.common import read_json
    root = tmp_path / 'staging'
    stage = root / '.work' / 'run-one'
    for name in ('ratings.parquet', 'movies.parquet'):
        (root / name).mkdir(parents=True)
        (root / name / 'old').write_text('previous dataset')
        (stage / name).mkdir(parents=True)
        (stage / name / 'new').write_text('current dataset')
    cfg = {'paths': {'staging': str(root), 'state': str(tmp_path / 'state'), 'reports': str(tmp_path / 'reports')}}
    metrics = {'source_sha256': {'ratings': 'example'}}
    replace = pipeline.os.replace
    def interrupt(source, destination):
        if interruption == 'move' and Path(source) == stage / 'movies.parquet':
            raise OSError('Simulated interrupted dataset publication')
        return replace(source, destination)
    atomic = pipeline.atomic_json
    def interrupt_manifest(path, value):
        if interruption == 'manifest' and Path(path) == root / 'manifest.json':
            raise OSError('Simulated interrupted dataset publication')
        return atomic(path, value)
    monkeypatch.setattr(pipeline.os, 'replace', interrupt)
    monkeypatch.setattr(pipeline, 'atomic_json', interrupt_manifest)
    with pytest.raises(OSError, match='interrupted'):
        pipeline.publish_staging(cfg, stage, metrics, 'run-one')
    monkeypatch.setattr(pipeline.os, 'replace', replace)
    monkeypatch.setattr(pipeline, 'atomic_json', atomic)
    pipeline.publish_staging(cfg, stage, metrics, 'run-one')
    assert read_json(root / 'manifest.json')['run_id'] == 'run-one'
    for name in ('ratings.parquet', 'movies.parquet'):
        assert (root / name / 'new').exists()
        assert not (root / name / 'old').exists()


def test_live_resume_requires_separate_metadata_refresh(cfg, monkeypatch):
    from pipeline import run
    monkeypatch.setenv('TMDB_TOKEN', 'private-test-token')
    cfg['synthetic'] = False
    with pytest.raises(ValueError, match='refresh'):
        run(cfg, offline=False, resume_run='prior')


def test_load_retry_after_publication_preserves_committed_database(cfg, monkeypatch):
    import duckdb
    import pipeline
    from utils.common import atomic_json, checksum, utcnow, sqlpath
    stage = Path(cfg['paths']['staging']) / '.work' / 'retry'
    statements = {
        'ratings': "SELECT 1 user_id,1 movie_id,3.5 rating,1000000000::BIGINT timestamp,'event-one' rating_event_id,TIMESTAMP '2001-09-09 01:46:40' rating_timestamp,20010909 date_key",
        'movies': "SELECT 1 movie_id,'Film (2001)' source_title,'Film' title,2001 release_year,'Drama' genres",
        'links': "SELECT 1 movie_id,'tt0000001' imdb_id,101 tmdb_id",
        'tags': "SELECT 1 user_id,1 movie_id,'tag' source_tag,'tag' tag,1000000000::BIGINT timestamp",
    }
    with duckdb.connect() as con:
        for name, sql in statements.items():
            sql = sql.replace('BIGINT timestamp', 'BIGINT AS "timestamp"')
            directory = stage / (name + '.parquet')
            directory.mkdir(parents=True)
            con.execute(f"COPY ({sql}) TO '{sqlpath(directory / 'part.parquet')}' (FORMAT PARQUET)")
    metrics = {'raw_ratings': 1, 'retained_ratings': 1, 'reconciliation': True,
               'created_at': utcnow(), 'stage': str(stage),
               'source_sha256': {name: checksum(Path(cfg['paths']['raw_movielens']) / (name + '.csv')) for name in statements}}
    atomic_json(Path(cfg['paths']['state']) / 'retry-job.json', {
        'run_id': 'retry', 'stage': str(stage), 'metrics': metrics, 'payloads': [],
        'completed_steps': ['extract', 'transform']})
    publish = pipeline.publish_staging
    def interrupt(*args):
        publish(*args)
        raise OSError('Interrupted after publication')
    monkeypatch.setattr(pipeline, 'publish_staging', interrupt)
    with pytest.raises(OSError, match='after publication'):
        pipeline.execute_stage(cfg, 'load', 'retry')
    committed = checksum(cfg['paths']['warehouse'])
    monkeypatch.setattr(pipeline, 'publish_staging', publish)
    result = pipeline.execute_stage(cfg, 'load', 'retry')
    assert result['warehouse']['ratings'] == 1
    assert checksum(cfg['paths']['warehouse']) == committed
