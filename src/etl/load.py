import hashlib
import json
import os
import uuid
from pathlib import Path
import duckdb
from utils.common import sqlpath, utcnow, atomic_json, writer_lock
from etl.data_quality import validate

ROOT = Path(__file__).resolve().parents[2]
RATING_BATCH_SIZE = 500_000


def connect(cfg, path=None, read_only=False):
    con = duckdb.connect(str(path or cfg['paths']['warehouse']), read_only=read_only)
    con.execute(f"SET threads={int(cfg['warehouse']['threads'])}")
    con.execute(f"SET memory_limit='{cfg['warehouse']['memory_limit']}'")
    # Rating rows are explicitly ordered by rowid in bounded batches. Keeping
    # DuckDB's implicit insertion order uses extra memory during large commits.
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET TimeZone='UTC'")
    return con


def stage_path(stage, name):
    """New readable datasets, with support for recorded pre-refactor staging."""
    path = Path(stage) / (name + '.parquet')
    return path if path.exists() else Path(stage) / name


def apply_metadata(con, payloads, stage=None):
    if stage is not None and stage_path(stage, 'tmdb_movies').exists():
        con.execute(f"CREATE TEMP TABLE incoming_metadata AS SELECT * FROM read_parquet('{sqlpath(stage_path(stage,'tmdb_movies'))}/*.parquet')")
        try:
            con.execute((ROOT/'warehouse/load_warehouse.sql').read_text().split('-- SCD TYPE 3')[1])
        finally:
            con.execute('DROP TABLE incoming_metadata')
        return
    con.execute('CREATE TEMP TABLE incoming_metadata(tmdb_id INTEGER,runtime INTEGER,original_language VARCHAR,title VARCHAR,release_date DATE,genres VARCHAR,popularity DOUBLE,vote_average DOUBLE,vote_count BIGINT,fetched_at TIMESTAMPTZ,payload_hash VARCHAR)')
    rows = []
    for p in payloads:
        rows.append((p['id'],p.get('runtime'),p.get('original_language'),p.get('title'),p.get('release_date') or None,json.dumps(p.get('genres',[])),p.get('popularity'),p.get('vote_average'),p.get('vote_count'),p['fetched_at'],p.get('payload_hash') or hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()))
    try:
        if rows:
            con.executemany('INSERT INTO incoming_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
            con.execute((ROOT/'warehouse/load_warehouse.sql').read_text().split('-- SCD TYPE 3')[1])
    finally:
        con.execute('DROP TABLE incoming_metadata')


def load(cfg, stage, metrics, payloads, run_id):
    destination = Path(cfg['paths']['warehouse'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.with_name(destination.stem+f'.{run_id}.{uuid.uuid4().hex[:6]}.candidate.duckdb')
    progress_path = Path(cfg['paths']['reports'])/'quality'/f'{run_id}-load-progress.json'
    progress = {'run_id': run_id, 'candidate': str(candidate),
                'duckdb_version': duckdb.__version__,
                'warehouse_resources': dict(cfg['warehouse']), 'started_at': utcnow()}

    def phase(name, status='running'):
        progress.update(phase=name, status=status, updated_at=utcnow())
        atomic_json(progress_path, progress)
        print(f'Warehouse load: {name} ({status})', flush=True)

    with writer_lock(destination):
        # Build fresh facts instead of copying obsolete fact pages on every reload.
        # Copy dimension keys/history and ETL provenance from the published database.
        phase('open candidate')
        con = connect(cfg,candidate)
        try:
            phase('begin transaction')
            con.execute('BEGIN')
            schema = (ROOT/'warehouse/schema.sql').read_text()
            if destination.exists():
                phase('read published dimension keys')
                con.execute(f"ATTACH '{sqlpath(destination)}' AS previous (READ_ONLY)")
                known = {'DimUser','DimMovie','DimDate','DimGenre','BridgeMovieGenre','FactRatings','ETLRun','MovieMonthAggregate'}
                tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='previous'").fetchall()}
                if tables - known:
                    raise ValueError(f'Preserve unexpected warehouse tables before rebuilding: {sorted(tables-known)}')
                for sequence, table, key in [('user_seq','DimUser','user_key'), ('movie_seq','DimMovie','movie_key'), ('genre_seq','DimGenre','genre_key')]:
                    next_key = con.execute(f'SELECT coalesce(max({key}),0)+1 FROM previous.{table}').fetchone()[0]
                    schema = schema.replace(f'CREATE SEQUENCE {sequence} START 1;', f'CREATE SEQUENCE {sequence} START {next_key};')
            phase('create schema')
            con.execute(schema)
            if destination.exists():
                phase('copy dimension history and provenance')
                for table in ('DimUser','DimMovie','DimDate','DimGenre','ETLRun'):
                    con.execute(f'INSERT INTO {table} SELECT * FROM previous.{table}')
            for name in ['ratings','movies','links','tags']:
                con.execute(f"CREATE TEMP VIEW stage_{name} AS SELECT * FROM read_parquet('{sqlpath(stage_path(stage,name))}/*.parquet')")
            phase('load dimensions and prepare rating input')
            con.execute((ROOT/'warehouse/load_warehouse.sql').read_text().split('-- SCD TYPE 3')[0])
            prepared = con.execute('SELECT count(*) FROM _load_ratings').fetchone()[0]
            if prepared != metrics['retained_ratings']:
                raise ValueError('Preparing facts lost or multiplied ratings')
            con.execute('COMMIT')
            con.execute('CHECKPOINT')
            con.close()
            # Every transaction writes only to the unpublished candidate. Reopening
            # releases cached ART index buffers between commits; one giant commit
            # exhausts memory when merging the full rating primary-key index.
            progress.update(total_ratings=prepared, committed_ratings=0,
                            rating_batch_size=RATING_BATCH_SIZE)
            for start in range(0, prepared, RATING_BATCH_SIZE):
                end = min(start + RATING_BATCH_SIZE, prepared)
                con = connect(cfg, candidate)
                phase(f'load ratings {start + 1:,}–{end:,} of {prepared:,}')
                con.execute('BEGIN')
                con.execute('''INSERT INTO FactRatings
                    SELECT rating_event_id,user_key,movie_key,date_key,rating,rating_timestamp
                    FROM _load_ratings WHERE rowid >= ? AND rowid < ? ORDER BY rowid''',
                    [start, end])
                con.execute('COMMIT')
                con.execute('CHECKPOINT')
                con.close()
                progress['committed_ratings'] = end
                phase(f'committed {end:,} of {prepared:,} ratings')
            con = connect(cfg, candidate)
            con.execute('BEGIN')
            con.execute('DROP TABLE _load_ratings')
            phase('apply staged movie metadata')
            apply_metadata(con,payloads,stage)
            phase('validate candidate')
            result = validate(con)
            if result['ratings'] != metrics['retained_ratings']:
                raise ValueError('Bulk load lost or multiplied ratings')
            con.execute('INSERT INTO ETLRun VALUES (?,?,?,?,?,?,?)',[run_id,'full',metrics['created_at'],utcnow(),'success',json.dumps({'ratings':metrics['raw_ratings'],'source_sha256':metrics['source_sha256']}),json.dumps(result)])
            phase('commit candidate')
            con.execute('COMMIT')
            phase('checkpoint candidate')
            con.execute('CHECKPOINT')
        except BaseException as error:
            progress['error_type'] = type(error).__name__
            phase(progress['phase'], 'failed')
            con.close()
            raise
        con.close()
        phase('publish candidate')
        os.replace(candidate,destination)
        atomic_json(Path(cfg['paths']['reports'])/'quality'/'warehouse_latest.json',{'run_id':run_id,**result})
        phase('published', 'success')
    return result
