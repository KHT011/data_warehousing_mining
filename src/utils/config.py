"""Small, explicit configuration for the local Docker project."""
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def resource_integer(name, default):
    value = os.environ.get(name, str(default)).strip()
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f'{name} must be a positive integer')
    return int(value)


def resource_memory(name, default, pattern):
    value = os.environ.get(name, default).strip()
    if not re.fullmatch(pattern, value, re.IGNORECASE):
        raise ValueError(f'{name} has an invalid memory size; expected a value like {default}')
    return value


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
        'spark': {'master': 'local[2]', 'shuffle_partitions': 8, 'driver_memory': '3g'},
        'warehouse': {'threads': 1, 'memory_limit': '4GB'},
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
    # Explicit environment overrides also apply to custom config files.
    # Values stored in each run's config preserve the effective resource setup.
    if not path or 'SPARK_CORES' in os.environ:
        cfg['spark']['master'] = f"local[{resource_integer('SPARK_CORES', 2)}]"
    cfg['spark']['shuffle_partitions'] = resource_integer(
        'SPARK_SHUFFLE_PARTITIONS', cfg['spark']['shuffle_partitions'])
    cfg['spark']['driver_memory'] = resource_memory(
        'SPARK_DRIVER_MEMORY', cfg['spark']['driver_memory'], r'[1-9][0-9]*[mg]')
    cfg['warehouse']['threads'] = resource_integer(
        'DUCKDB_THREADS', cfg['warehouse']['threads'])
    cfg['warehouse']['memory_limit'] = resource_memory(
        'DUCKDB_MEMORY_LIMIT', cfg['warehouse']['memory_limit'], r'[1-9][0-9]*(?:MB|GB|MiB|GiB)')
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
