import csv
import random
from pathlib import Path


def generate(cfg, metadata=False):
    """Isolated synthetic fixture: never writes into real MovieLens paths."""
    if not cfg.get('synthetic'):
        raise ValueError('Synthetic generation requires --smoke isolation')
    root = Path(cfg['paths']['raw_movielens'])
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    def write(name, header, rows):
        with (root / name).open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f,lineterminator='\n'); w.writerow(header); w.writerows(rows)
    write('movies.csv', ['movieId','title','genres'], [(m, f'Synthetic Film {m} ({1990+m%20})', ['Comedy|Drama','Action','(no genres listed)'][m%3]) for m in range(1,31)])
    write('links.csv', ['movieId','imdbId','tmdbId'], [(m,f'{m:07}',m+100) for m in range(1,31)])
    rows = [(u,m,rng.randrange(1,11)/2,1000000000+i*3600) for i,(u,m) in enumerate(( (u,m) for u in range(1,61) for m in range(1,31))) ]
    rows += [rows[0], (1,1,8,1000000001), (1,999,3,1000000002), ('bad',1,3,1000000003)]
    write('ratings.csv', ['userId','movieId','rating','timestamp'], rows)
    write('tags.csv', ['userId','movieId','tag','timestamp'], [(1,1,' café ',1000000000),(61,2,'tag only',1000000001)])
    (root / 'README.txt').write_text('Synthetic fixture, not MovieLens; seed 42. Includes malformed, duplicate and orphan rows.\n')
    if metadata:
        import hashlib
        import json
        from utils.common import atomic_json
        payload = {'id': 101, 'title': 'Synthetic Film 1', 'runtime': 90,
                   'original_language': 'en', 'genres': [{'id': 18, 'name': 'Drama'}]}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        fetched = '2025-01-01T00:00:00+00:00'
        path = Path(cfg['paths']['raw_tmdb']) / 'synthetic' / '101-en-US.json'
        atomic_json(path, {'payload': payload, 'language': 'en-US', 'fetched_at': fetched,
                          'payload_hash': digest, 'synthetic': True})
        atomic_json(Path(cfg['paths']['state']) / 'tmdb_manifest.json', {
            '101:en-US': {'tmdb_id': 101, 'language': 'en-US', 'status': 'success',
                          'snapshot': str(path), 'fetched_at': fetched, 'payload_hash': digest}})
