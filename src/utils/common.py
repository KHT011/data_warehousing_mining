import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def checksum(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sqlpath(path):
    return str(Path(path).resolve()).replace('\\', '/').replace("'", "''")


@contextmanager
def writer_lock(path):
    path = Path(str(path) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    locked = False
    try:
        if os.name=='nt':
            import msvcrt
            handle.seek(0)
            if path.stat().st_size==0:handle.write(b'0');handle.flush()
            handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError(f'Another writer holds {path}') from None
        else:
            import fcntl
            try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError(f'Another writer holds {path}') from None
        locked=True
        handle.seek(0);handle.truncate();handle.write(str(os.getpid()).encode());handle.flush()
        yield
    finally:
        if locked:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()
        # Keep the sidecar inode stable. The OS releases ownership on process death.
