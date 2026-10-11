"""Record real full-data and Airflow acceptance evidence; no live API calls.

Executed inside Docker during implementation, not part of the normal pipeline.
"""
import base64
import json
from pathlib import Path
import sys
import time
import urllib.request
import uuid
import subprocess

from utils.common import atomic_json, utcnow
from utils.config import load_config


def warehouse_signature():
    from etl.load import connect, validate
    with connect(load_config(), read_only=True) as con:
        return {
            'validation': validate(con),
            'facts': con.execute('SELECT count(*),sum(rating),bit_xor(hash(rating_event_id,user_key,movie_key,date_key,rating,rating_timestamp)) FROM FactRatings').fetchone(),
            'movies': con.execute('SELECT count(*),bit_xor(hash(movie_id,movie_key)) FROM DimMovie').fetchone(),
            'users': con.execute('SELECT count(*),bit_xor(hash(user_id,user_key)) FROM DimUser').fetchone(),
            'metadata': con.execute('SELECT count(*),bit_xor(hash(movie_id,runtime,previous_runtime,original_language,previous_original_language,metadata_fetched_at)) FROM DimMovie').fetchone(),
        }


def verify_airflow():
    password = Path('/opt/airflow/standalone_admin_password.txt').read_text().strip()
    auth = base64.b64encode(('admin:' + password).encode()).decode()
    def request(path, method='GET', body=None):
        req = urllib.request.Request('http://localhost:8080/api/v1' + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    dag = 'movielens_pipeline'
    request('/dags/' + dag, 'PATCH', {'is_paused': False})
    identifier = 'simplified_smoke_' + uuid.uuid4().hex[:12]
    started = time.perf_counter()
    request(f'/dags/{dag}/dagRuns', 'POST', {'dag_run_id': identifier, 'conf': {'smoke': True, 'live': False}})
    while time.perf_counter() - started < 600:
        record = request(f'/dags/{dag}/dagRuns/{identifier}')
        if record['state'] in ('success', 'failed'):
            tasks = request(f'/dags/{dag}/dagRuns/{identifier}/taskInstances')['task_instances']
            evidence = {'created_at': utcnow(), 'dag': dag, 'run_id': identifier,
                        'state': record['state'], 'seconds': time.perf_counter() - started,
                        'synthetic': True, 'live': False,
                        'tasks': [{key: item.get(key) for key in ('task_id', 'state', 'duration', 'try_number')} for item in tasks]}
            atomic_json('reports/results/airflow.json', evidence)
            print(json.dumps(evidence, indent=2))
            assert record['state'] == 'success' and len(tasks) == 5
            assert all(item['state'] == 'success' for item in tasks)
            return
        time.sleep(3)
    raise TimeoutError('Airflow smoke run did not complete within 10 minutes')


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'full':
        before = warehouse_signature()
        atomic_json('reports/results/before-warehouse.json', before)
        started = time.perf_counter()
        with Path('reports/results/full-run.log').open('w') as log:
            subprocess.run([sys.executable, 'run_pipeline.py'], stdout=log, stderr=subprocess.STDOUT, check=True)
        after = warehouse_signature()
        assert before == after, 'Full warehouse count, key, rating or metadata signature changed'
        atomic_json('reports/results/full-comparison.json', {'created_at': utcnow(), 'matches': True,
                    'seconds': time.perf_counter() - started, 'signature': after})
        print(json.dumps({'matches': True, 'seconds': time.perf_counter()-started, 'signature': after}, indent=2))
    elif mode == 'airflow':
        verify_airflow()
    elif mode == 'before':
        atomic_json('reports/results/before-warehouse.json', warehouse_signature())
        print('Full warehouse baseline signature recorded.')
    elif mode == 'after':
        before = json.loads(Path('reports/results/before-warehouse.json').read_text())
        after = json.loads(json.dumps(warehouse_signature()))
        assert before == after, 'Full warehouse count, key, rating or metadata signature changed'
        atomic_json('reports/results/full-comparison.json', {'created_at': utcnow(), 'matches': True, 'signature': after})
        print(json.dumps(after, indent=2))
