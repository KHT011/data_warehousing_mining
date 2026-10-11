import csv
import platform
from pathlib import Path
from utils.common import checksum, atomic_json, utcnow, sqlpath

CONTRACTS = {
    'ratings': ['userId','movieId','rating','timestamp'],
    'movies': ['movieId','title','genres'],
    'links': ['movieId','imdbId','tmdbId'],
    'tags': ['userId','movieId','tag','timestamp'],
}


def validate_sources(cfg):
    root = Path(cfg['paths']['raw_movielens'])
    for name, fields in CONTRACTS.items():
        with (root / f'{name}.csv').open(encoding='utf-8', newline='') as f:
            if next(csv.reader(f), None) != fields:
                raise ValueError(f'{name}: schema mismatch; expected {fields}')
    return root


def audit(cfg):
    import duckdb
    root = validate_sources(cfg)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{cfg['warehouse']['memory_limit']}'")
    con.execute(f"SET threads={int(cfg['warehouse']['threads'])}")
    result = {'created_at': utcnow(), 'synthetic': cfg['synthetic'], 'python': platform.python_version(), 'duckdb': duckdb.__version__, 'settings': cfg, 'files': {}}
    for file in sorted(root.glob('*.csv')):
        name = file.stem
        table='"'+name.replace('"','""')+'"'
        # Materialize contracts once; parse rejects are counted explicitly, not silently lost.
        malformed=0;reject_samples=[]
        if name in CONTRACTS:
            columns='{'+','.join(f"'{field}':'VARCHAR'" for field in CONTRACTS[name])+'}'
            rejects=f'audit_rejects_{name}'
            con.execute(f"CREATE TEMP TABLE {table} AS SELECT * FROM read_csv('{sqlpath(file)}', delim=',', quote='\"', escape='\"', header=true, auto_detect=false, columns={columns}, store_rejects=true, rejects_table='{rejects}', rejects_scan='audit_scan_{name}', ignore_errors=true)")
            malformed=con.execute(f'SELECT count(DISTINCT line) FROM {rejects}').fetchone()[0]
            reject_samples=[dict(zip(['line','csv_line','error_message'],r)) for r in con.execute(f'SELECT line,csv_line,error_message FROM {rejects} LIMIT 5').fetchall()]
        else:
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv('{sqlpath(file)}', delim=',', header=true, all_varchar=true)")
        fields = [r[0] for r in con.execute(f'DESCRIBE {table}').fetchall()]
        parsed=con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
        result['files'][name] = {'path': str(file), 'bytes': file.stat().st_size, 'sha256': checksum(file), 'columns': fields, 'rows':parsed+malformed,'parsed_rows':parsed,'malformed_rows':malformed,'parse_reject_samples':reject_samples,'statistics_scope':'successfully parsed rows; malformed records counted separately'}
        if name in CONTRACTS:
            result['files'][name]['nulls'] = dict(zip(fields, con.execute('SELECT ' + ','.join(f'count(*) FILTER (WHERE "{f}" IS NULL)' for f in fields) + f' FROM {table}').fetchone()))
            result['files'][name]['exact_duplicates'] = con.execute(f'SELECT (SELECT count(*) FROM {table}) - count(*) FROM (SELECT DISTINCT * FROM {table})').fetchone()[0]
    q = lambda sql: con.execute(sql).fetchall()
    result['ratings'] = {
        'unique_users': q('SELECT count(DISTINCT userId) FROM ratings')[0][0],
        'unique_movies': q('SELECT count(DISTINCT movieId) FROM ratings')[0][0],
        'rating_distribution': q('SELECT rating,count(*) FROM ratings GROUP BY rating ORDER BY rating'),
        'timestamp_range': q('SELECT min(try_cast(timestamp AS BIGINT)),max(try_cast(timestamp AS BIGINT)) FROM ratings')[0],
        'duplicate_user_movie_groups': q('SELECT count(*) FROM (SELECT userId,movieId FROM ratings GROUP BY ALL HAVING count(*)>1)')[0][0],
        'conflicting_event_groups': q('SELECT count(*) FROM (SELECT userId,movieId,timestamp FROM ratings GROUP BY ALL HAVING count(DISTINCT rating)>1)')[0][0],
        'orphan_rows': q('SELECT count(*) FROM ratings r ANTI JOIN movies m USING(movieId)')[0][0],
        'tag_only_users': q('SELECT count(*) FROM (SELECT DISTINCT userId FROM tags EXCEPT SELECT DISTINCT userId FROM ratings)')[0][0],
        'tagged_movies': q('SELECT count(DISTINCT movieId) FROM tags')[0][0],
        'unknown_genre_movies': q("SELECT count(*) FROM movies WHERE genres='(no genres listed)' OR genres IS NULL")[0][0],
    }
    con.close()
    atomic_json(Path(cfg['paths']['reports']) / 'quality' / 'source_audit.json', result)
    return result


import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from utils.common import atomic_json, read_json, utcnow


class TMDBClient:
    def __init__(self,state_dir,snapshot_dir=None,token=None,language='en-US',base_url='https://api.themoviedb.org/3',session=None,sleep=time.sleep,max_attempts=5,requests_per_second=5,timeout=(10,30)):
        self.token=token if token is not None else os.environ.get('TMDB_TOKEN','')
        if not self.token:raise ValueError('Explicit live extraction requires TMDB_TOKEN')
        self.state=Path(state_dir);self.snapshots=Path(snapshot_dir or self.state/'snapshots')
        self.manifest_path=self.state/'tmdb_manifest.json';self.manifest=read_json(self.manifest_path,{})
        self.language=language;self.base_url=base_url;self.session=session or requests.Session();self.sleep=sleep
        self.max_attempts=max_attempts;self.interval=1./requests_per_second;self.timeout=tuple(timeout)

    def key(self,tmdb_id):return f'{int(tmdb_id)}:{self.language}'

    def fetch(self,tmdb_id,movie_ids,run_id,refresh=False):
        key=self.key(tmdb_id);previous=self.manifest.get(key,{})
        if not refresh and previous.get('snapshot'):
            envelope=read_json(previous['snapshot'])
            if envelope and envelope['language']==self.language:return envelope
        endpoint=f'/movie/{int(tmdb_id)}'
        entry={**previous,'tmdb_id':int(tmdb_id),'language':self.language,'status':'pending','last_error':None}
        self.manifest[key]=entry
        atomic_json(self.manifest_path,self.manifest)
        for attempt in range(self.max_attempts):
            entry['attempt_count']=entry.get('attempt_count',0)+1
            self.sleep(self.interval)
            retry_after=0
            try:
                response=self.session.get(self.base_url+endpoint,headers={'Authorization':'Bearer '+self.token},params={'language':self.language},timeout=self.timeout)
                status=response.status_code
                if status in (401,403):
                    entry.update(status='authentication_failed',last_error=f'HTTP {status}')
                    atomic_json(self.manifest_path,self.manifest)
                    raise PermissionError(f'TMDB authentication failed: HTTP {status}')
                if status==404:
                    entry.update(status='not_found',last_error='HTTP 404')
                    atomic_json(self.manifest_path,self.manifest)
                    return None
                if status==429 or 500<=status<600:
                    value=response.headers.get('Retry-After','0')
                    try:retry_after=float(value)
                    except ValueError:
                        try:retry_after=max(0,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
                        except (ValueError,TypeError):retry_after=0
                    entry['last_error']=f'HTTP {status}'
                elif status==200:
                    try:payload=response.json()
                    except ValueError:raise ValueError('TMDB response is not JSON') from None
                    if not isinstance(payload,dict) or payload.get('id')!=int(tmdb_id) or not isinstance(payload.get('title'),str):
                        raise ValueError('TMDB movie identity/schema mismatch')
                    fetched=utcnow();digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
                    envelope={'tmdb_id':int(tmdb_id),'movie_ids':movie_ids,'endpoint':endpoint,'language':self.language,'fetched_at':fetched,'http_status':status,'run_id':run_id,'payload_hash':digest,'payload':payload}
                    path=self.snapshots/run_id/f'{tmdb_id}-{self.language}.json'
                    atomic_json(path,envelope)
                    entry.update(status='success',snapshot=str(path),fetched_at=fetched,payload_hash=digest,last_error=None)
                    atomic_json(self.manifest_path,self.manifest)
                    return envelope
                else:
                    raise ValueError(f'Unexpected TMDB HTTP status {status}')
            except (requests.Timeout,requests.ConnectionError):
                # Exception messages can contain request details. Persist only a safe category.
                entry['last_error']='transport_error'
            except (ValueError,PermissionError):
                if entry['status']!='authentication_failed':entry.update(status='invalid_response',last_error='invalid_response')
                atomic_json(self.manifest_path,self.manifest)
                raise
            entry['status']='retryable_failure';atomic_json(self.manifest_path,self.manifest)
            if attempt+1<self.max_attempts:self.sleep(max(retry_after,2**attempt+random.random()))
        raise RuntimeError(f'TMDB retry budget exhausted for movie {tmdb_id}')


def cached_payloads(cfg):
    manifest=read_json(Path(cfg['paths']['state'])/'tmdb_manifest.json',{})
    results=[]
    for entry in manifest.values():
        # Last successful snapshot is valid even when the latest attempt failed.
        if entry.get('snapshot') and entry.get('language')==cfg['tmdb']['language']:
            envelope=read_json(entry['snapshot'])
            if envelope:
                results.append({**envelope['payload'],'fetched_at':envelope['fetched_at'],'payload_hash':envelope['payload_hash']})
    return results


def extract(cfg,run_id,limit=500,incremental=False):
    import csv
    mappings={}
    with (Path(cfg['paths']['raw_movielens'])/'links.csv').open(newline='',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:tmdb_id=int(row['tmdbId']);movie_id=int(row['movieId'])
            except (ValueError,TypeError):continue
            if tmdb_id>0:mappings.setdefault(tmdb_id,[]).append(movie_id)
    options=cfg['tmdb'];client=TMDBClient(cfg['paths']['state'],cfg['paths']['raw_tmdb'],language=options['language'],base_url=options['base_url'],max_attempts=options['max_attempts'],requests_per_second=options['requests_per_second'],timeout=options['timeout'])
    selected=sorted(mappings)
    if incremental:
        cutoff=datetime.now(timezone.utc)-timedelta(days=options['stale_days'])
        selected=[i for i in selected if client.manifest.get(client.key(i),{}).get('status')!='success' or datetime.fromisoformat(client.manifest[client.key(i)]['fetched_at'])<cutoff]
    if limit!='all':selected=selected[:int(limit)]
    for tmdb_id in selected:client.fetch(tmdb_id,mappings[tmdb_id],run_id,refresh=incremental)
    return cached_payloads(cfg),{'mode':'bounded_stale_refresh' if incremental else 'initial_resumable','selected_ids':len(selected),'mapped_tmdb_ids':len(mappings),'successful_cached_ids':len(cached_payloads(cfg)),'live':True}
