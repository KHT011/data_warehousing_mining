import hashlib
import re
from pathlib import Path


def validate(con):
    """Fail publication on broken facts, references or genre allocation."""
    root = Path(__file__).resolve().parents[2]
    checks = dict(con.execute((root / 'sql/warehouse_checks.sql').read_text()).fetchall())
    if any(checks.values()):
        raise ValueError(f'Critical warehouse checks: {checks}')
    return {
        'checks': checks,
        'ratings': con.execute('SELECT count(*) FROM FactRatings').fetchone()[0],
        'users': con.execute('SELECT count(*) FROM DimUser').fetchone()[0],
        'movies': con.execute('SELECT count(*) FROM DimMovie').fetchone()[0],
    }


def parse_title(source):
    match = re.search(r'\s*\((\d{4})\)$', source)
    return (source[:match.start()].strip(), int(match[1])) if match else (source, None)


def rating_event_id(user_id, movie_id, timestamp):
    return hashlib.sha256(f'{user_id}:{movie_id}:{timestamp}'.encode()).hexdigest()


def scd3(old, payload, observed_at):
    result = dict(old)
    if payload is None:
        return result
    initialized = 'runtime' in old
    for field, change_field in [('runtime', 'runtime_changed_at'), ('original_language', 'language_changed_at')]:
        value = payload.get(field)
        result.setdefault('previous_' + field, None)
        if initialized and old.get(field) != value:
            result['previous_' + field] = old.get(field)
            result[change_field] = observed_at
        result[field] = value
    return result
