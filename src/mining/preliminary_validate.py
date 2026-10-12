"""Independently reconcile the generated preliminary evidence."""
from pathlib import Path
import json
import pickle
import time
import duckdb
import numpy as np
import pandas as pd
from mining.preliminary import save_json, timestamp


def validate_result():
    begin = time.perf_counter()
    root = Path('reports/results/mining_preliminary')
    r = json.loads((root / 'latest.json').read_text())
    out = Path(r['results_directory'])
    features = pd.read_parquet(Path(r['derived_data_directory']) / 'user_features.parquet')
    labels = pd.read_parquet(Path(r['derived_data_directory']) / 'user_clusters.parquet')
    assert len(features) == len(labels) == r['eda']['rating_users']
    assert features.user_key.is_unique and labels.user_key.is_unique
    assert np.array_equal(features.user_key.to_numpy(), labels.user_key.to_numpy())
    with (Path(r['derived_data_directory']) / 'clustering_model.pkl').open('rb') as f:
        model = pickle.load(f)
    predictions = model['model'].predict(model['scaler'].transform(features[model['features']]))
    assert np.array_equal(predictions, labels.cluster.to_numpy())
    genre = [f for f in model['features'] if f.startswith('genre_')]
    assert np.allclose(features[genre].sum(axis=1), 1)
    assert np.isfinite(features[model['features']]).all().all()
    assert int(features.rating_count.sum()) == r['eda']['ratings']
    for row in r['clustering']['candidates']:
        assert sum(row['sizes'].values()) == len(features)
    expected = {m['model']:m for m in r['baselines']['metrics'] if m['split']=='test'}
    global_mean = r['baselines']['training_global_mean']
    train_end = pd.Timestamp(r['baselines']['train_end_exclusive_utc']).to_pydatetime()
    test_start = pd.Timestamp(r['baselines']['test_start_inclusive_utc']).to_pydatetime()
    totals = {name:{'sse':0.,'absolute_error':0.} for name in expected}
    n = 0
    c = duckdb.connect(r['warehouse'], read_only=True)
    c.execute("SET threads=1; SET memory_limit='2GB'; SET preserve_insertion_order=false")
    signature = c.execute('SELECT count(*),sum(rating) FROM FactRatings').fetchone()
    assert signature == (r['warehouse_signature']['ratings'], r['warehouse_signature']['rating_sum'])
    # Independent NumPy error accumulation over every test event. The original
    # SQL metrics are not reused to calculate these error totals.
    cursor = c.execute('''WITH training AS (
        SELECT movie_key,avg(rating) prediction FROM FactRatings
        WHERE rating_timestamp < ? GROUP BY movie_key)
        SELECT f.rating,coalesce(t.prediction,?) prediction FROM FactRatings f
        LEFT JOIN training t USING(movie_key) WHERE f.rating_timestamp >= ?''',
        [train_end, global_mean, test_start])
    while True:
        rows = cursor.fetchmany(100000)
        if not rows:
            break
        a = np.asarray(rows, dtype=np.float64)
        assert np.isfinite(a).all() and ((a >= .5) & (a <= 5)).all()
        n += len(a)
        for name, pred in [('global_average', global_mean), ('movie_average', a[:,1])]:
            errors = a[:,0] - pred
            totals[name]['sse'] += float(np.dot(errors, errors))
            totals[name]['absolute_error'] += float(np.abs(errors).sum())
    computed = {}
    for name, sums in totals.items():
        assert n == expected[name]['ratings']
        values = {'rmse':float(np.sqrt(sums['sse']/n)), 'mae':sums['absolute_error']/n}
        for metric,value in values.items():
            assert np.isclose(value, expected[name][metric], atol=1e-10, rtol=1e-10)
        computed[name] = values
    c.close()
    nb = json.loads(Path('notebooks/05_mining_preliminary.ipynb').read_text())
    code = [cell for cell in nb['cells'] if cell['cell_type']=='code']
    assert all(cell['execution_count'] is not None for cell in code)
    assert not any(o.get('output_type')=='error' for cell in code for o in cell['outputs'])
    result = {'created_at':timestamp(), 'run_id':r['run_id'], 'status':'success',
        'rating_count_reconciled':int(features.rating_count.sum()),
        'full_user_assignments_reconciled':len(features),
        'saved_model_reproduces_every_assignment':True,
        'all_genre_shares_sum_to_one':True, 'finite_features':True,
        'all_test_events_independently_checked':n,
        'numpy_test_metrics_match_sql':computed,
        'executed_notebook_code_cells':len(code), 'notebook_errors':0,
        'warehouse_count_sum_unchanged':True,
        'seconds':time.perf_counter()-begin}
    save_json(out / 'verification.json', result)
    save_json(root / 'verification.json', result)
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__ == '__main__':
    validate_result()
