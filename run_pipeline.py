"""One entry point: run, refresh, olap, ui or isolated offline smoke."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='run',
                        choices=['run', 'refresh', 'olap', 'ui', 'smoke', 'stage'])
    parser.add_argument('step', nargs='?', choices=['extract', 'transform', 'load', 'validate', 'olap'])
    parser.add_argument('--live', action='store_true', help='Explicit TMDB access; network and token required')
    parser.add_argument('--tmdb-limit', default='500', help='Positive integer or all')
    parser.add_argument('--resume-run', help='Reuse fingerprint-validated staging from this recorded run')
    parser.add_argument('--smoke', action='store_true', help='Select isolated synthetic paths')
    parser.add_argument('--run-id', help='Airflow stage identifier (internal)')
    parser.add_argument('--config', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.tmdb_limit != 'all' and (not args.tmdb_limit.isdigit() or int(args.tmdb_limit) < 1):
        parser.error('--tmdb-limit must be a positive integer or all')
    if args.command == 'stage' and (not args.step or not args.run_id):
        parser.error('stage requires a step and --run-id')
    if args.run_id and (Path(args.run_id).name != args.run_id or args.run_id in ('.', '..')):
        parser.error('Invalid run identifier')
    os.chdir(ROOT)
    from utils.config import load_config
    from utils.common import writer_lock
    from pipeline import check_options, execute_stage, run
    cfg = load_config(args.config, smoke=args.smoke or args.command == 'smoke')
    check_options(cfg, offline=not args.live, resume_run=args.resume_run)
    if args.command in ('run', 'smoke', 'refresh'):
        if args.command == 'smoke':
            from etl.synthetic import generate
            generate(cfg, metadata=True)
        result = run(cfg, mode='incremental' if args.command == 'refresh' else 'full',
                     offline=not args.live, tmdb_limit=args.tmdb_limit,
                     resume_run=args.resume_run, analytics=args.command != 'refresh')
    elif args.command == 'stage':
        with writer_lock(Path(cfg['paths']['state']) / 'pipeline'):
            if cfg['synthetic'] and args.step == 'extract':
                from etl.synthetic import generate
                generate(cfg, metadata=True)
            result = execute_stage(cfg, args.step, args.run_id, offline=not args.live,
                                   tmdb_limit=args.tmdb_limit, resume_run=args.resume_run)
    elif args.command == 'olap':
        from analytics import benchmark, eda
        with writer_lock(Path(cfg['paths']['state']) / 'pipeline'):
            result = benchmark(cfg, **({'start_year': 2001, 'end_year': 2002, 'min_support': 5} if cfg['synthetic'] else {}))
            eda(cfg)
    else:
        from utils.duckdb_ui import start
        start(cfg)
        result = {'status': 'DuckDB UI closed; container remains running'}
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        if 'holds' in str(error):
            raise SystemExit('Close DuckDB UI or wait for the active pipeline before trying again.') from None
        raise
