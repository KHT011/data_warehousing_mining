"""Official UI with a same-port TCP relay; no Docker host-network setting.

The UI listens on container localhost:4213. Relay the bridge address:4213 to
localhost:4213, preserving browser origins. Compose publishes host localhost only.
"""
from contextlib import contextmanager
from pathlib import Path
import select
import signal
import socket
import socketserver
import threading

import duckdb
from utils.common import writer_lock


@contextmanager
def forwarding_server(bind_address, port, upstream):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                with socket.create_connection(upstream, timeout=10) as target:
                    target.settimeout(None)
                    sockets = (self.request, target)
                    while not self.server.stopping.is_set():
                        ready, _, _ = select.select(sockets, [], [], 1)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (target if source is self.request else self.request).sendall(data)
            except OSError:
                return

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server((bind_address, port), Handler) as server:
        server.stopping = threading.Event()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.stopping.set()
            server.shutdown()
            thread.join(timeout=5)


def start(cfg):
    warehouse = Path(cfg['paths']['warehouse']).resolve()
    if not warehouse.exists():
        raise FileNotFoundError('Run the pipeline before opening DuckDB UI.')
    stopping = threading.Event()
    previous_handlers = {event: signal.signal(event, lambda *_: stopping.set())
                         for event in (signal.SIGTERM, signal.SIGINT)}
    try:
        with writer_lock(Path(cfg['paths']['state']) / 'pipeline'), writer_lock(warehouse):
            with duckdb.connect() as con:
                con.execute('INSTALL ui')
                con.execute('LOAD ui')
                con.execute(f"SET memory_limit='{cfg['warehouse']['memory_limit']}'")
                con.execute(f"SET threads={int(cfg['warehouse']['threads'])}")
                escaped = str(warehouse).replace("'", "''")
                con.execute(f"ATTACH '{escaped}' AS movielens (READ_ONLY)")
                con.execute('USE movielens')
                con.execute('CALL start_ui_server()')
                try:
                    address = socket.gethostbyname(socket.gethostname())
                    with forwarding_server(address, 4213, ('localhost', 4213)):
                        print('DuckDB UI: http://localhost:4213 — Ctrl+C closes UI; container stays running.', flush=True)
                        stopping.wait()
                finally:
                    con.execute('CALL stop_ui_server()')
    finally:
        for event, handler in previous_handlers.items():
            signal.signal(event, handler)
