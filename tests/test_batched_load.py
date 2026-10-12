"""Exercise batch boundaries and publication safety without Spark or network."""
import json
from pathlib import Path

import duckdb
import pytest

from etl import load as loader
from utils.common import checksum


@pytest.fixture
def batch_input(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, 'RATING_BATCH_SIZE', 3)
    stage = tmp_path / 'stage'
    cfg = {'paths': {'warehouse': str(tmp_path / 'published.duckdb'),
                     'reports': str(tmp_path / 'reports')},
           'warehouse': {'threads': 1, 'memory_limit': '256MB'}}
    queries = {
        'ratings': """SELECT 'event-' || i AS rating_event_id, 1::INTEGER AS user_id,
            1::INTEGER AS movie_id, 20200101::INTEGER AS date_key, 4.0 AS rating,
            TIMESTAMP '2020-01-01' + i * INTERVAL '1 second' AS rating_timestamp
            FROM range(7) r(i)""",
        'movies': "SELECT 1 AS movie_id, 'Example (2000)' AS source_title, 'Example' AS title, 2000 AS release_year, 'Drama' AS genres",
        'links': "SELECT 1 AS movie_id, 'tt0000001' AS imdb_id, 101 AS tmdb_id",
        'tags': "SELECT 2 AS user_id",
    }
    with duckdb.connect() as con:
        for name, query in queries.items():
            folder = stage / (name + '.parquet')
            folder.mkdir(parents=True)
            con.execute(f"COPY ({query}) TO '{folder}/part.parquet' (FORMAT PARQUET)")
    metrics = {'retained_ratings': 7, 'raw_ratings': 7,
               'created_at': '2026-10-12T00:00:00Z', 'source_sha256': {}}
    return cfg, stage, metrics


def test_all_batches_and_partial_final_batch_are_published(batch_input):
    cfg, stage, metrics = batch_input
    result = loader.load(cfg, stage, metrics, [], 'batches')
    assert result['ratings'] == 7
    assert result['users'] == 2
    assert not any(result['checks'].values())
    with loader.connect(cfg, read_only=True) as con:
        assert con.execute('SELECT count(DISTINCT rating_event_id) FROM FactRatings').fetchone()[0] == 7
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='_load_ratings'").fetchone()[0] == 0
    progress = json.loads((Path(cfg['paths']['reports'])/'quality/batches-load-progress.json').read_text())
    assert progress['committed_ratings'] == 7
    assert progress['status'] == 'success'


def test_reload_preserves_keys_and_metadata_history(batch_input):
    cfg, stage, metrics = batch_input
    first = {'id':101, 'runtime':90, 'original_language':'en', 'fetched_at':'2026-10-10T00:00:00Z'}
    loader.load(cfg, stage, metrics, [first], 'initial')
    with loader.connect(cfg, read_only=True) as con:
        keys = con.execute('SELECT movie_key FROM DimMovie').fetchall()
    loader.load(cfg, stage, metrics, [{**first, 'runtime':95, 'fetched_at':'2026-10-11T00:00:00Z'}], 'repeat')
    with loader.connect(cfg, read_only=True) as con:
        assert con.execute('SELECT movie_key FROM DimMovie').fetchall() == keys
        assert con.execute('SELECT runtime,previous_runtime FROM DimMovie').fetchone() == (95, 90)
        assert con.execute('SELECT count(*) FROM FactRatings').fetchone()[0] == 7
        assert con.execute('SELECT count(*) FROM ETLRun').fetchone()[0] == 2


def test_duplicate_in_later_batch_keeps_published_file(batch_input):
    cfg, stage, metrics = batch_input
    loader.load(cfg, stage, metrics, [], 'good')
    before = checksum(cfg['paths']['warehouse'])
    part = stage/'ratings.parquet/part.parquet'
    with duckdb.connect() as con:
        con.execute(f"CREATE TABLE bad AS SELECT * FROM read_parquet('{part}')")
        con.execute("UPDATE bad SET rating_event_id='event-0' WHERE rating_event_id='event-6'")
        con.execute(f"COPY bad TO '{part}' (FORMAT PARQUET)")
    with pytest.raises(duckdb.ConstraintException):
        loader.load(cfg, stage, metrics, [], 'bad')
    assert checksum(cfg['paths']['warehouse']) == before
    progress = json.loads((Path(cfg['paths']['reports'])/'quality/bad-load-progress.json').read_text())
    assert progress['committed_ratings'] == 6
    assert progress['status'] == 'failed'
