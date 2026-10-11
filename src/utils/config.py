"""Small, explicit configuration for the local Docker project."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_config(path=None, smoke=False):
    cfg = {
        'project': {'seed': 42, 'timezone': 'UTC'},
        'paths': {
            'raw_movielens': 'data/raw',
            'raw_tmdb': 'data/raw/tmdb/snapshots',
            'staging': 'data/staging',
            'warehouse': 'warehouse/movielens.duckdb',
            'reports': 'reports', 'state': 'data/raw/tmdb/state',
            'processed': 'data/processed', 'models': 'data/processed/models',
        },
        'spark': {'master': 'local[2]', 'shuffle_partitions': 8, 'driver_memory': '4g'},
        'warehouse': {'threads': 2, 'memory_limit': '6GB'},
        'tmdb': {
            'base_url': 'https://api.themoviedb.org/3', 'language': 'en-US',
            'requests_per_second': 5, 'max_attempts': 5,
            'timeout': [10, 30], 'stale_days': 7,
        },
        # Retained for the inactive mining modules; the warehouse never imports them.
        'mining': {
            'train_fraction': .70, 'validation_fraction': .15,
            'regression_sample_limit': 1000000,
            'cluster_k_values': [2, 3, 4, 5, 6, 8], 'silhouette_sample_limit': 5000,
        },
    }
    if path:
        import yaml
        cfg = yaml.safe_load(Path(path).read_text())
    if smoke:
        cfg['paths'] = {
            'raw_movielens': 'data/smoke/raw',
            'raw_tmdb': 'data/smoke/raw/tmdb/snapshots',
            'staging': 'data/smoke/staging', 'warehouse': 'data/smoke/warehouse.duckdb',
            'reports': 'reports/smoke', 'state': 'data/smoke/raw/tmdb/state',
            'processed': 'data/smoke/processed', 'models': 'data/smoke/models',
        }
        cfg['mining']['regression_sample_limit'] = 10000
        cfg['mining']['silhouette_sample_limit'] = 100
    cfg['synthetic'] = smoke
    return cfg
