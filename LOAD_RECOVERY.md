# Recover the native DuckDB load failure

## Evidence and current boundary

- DAG run: `manual__2026-10-12T08:13:56+00:00`.
- Pipeline staging ID: `airflow-7ad6db2270f8de79ba22`.
- Extraction and transformation succeeded. Prepared Parquet datasets remain
  under `data/staging/.work/airflow-7ad6db2270f8de79ba22`.
- Load attempts 1–4 aborted with SIGABRT inside DuckDB 1.2.2. The native message
  was `Attempted to dereference unique_ptr that is NULL!`.
- Symbol inspection locates the crash in index vacuum during commit rollback.
  This identifies the failing engine path; the original commit error is still
  unknown. Increasing the budget from 3 GB / 2 threads to 4 GB / 1 thread did
  not resolve it. Container OOM counters remained zero.
- After the initial failures, the published warehouse was readable with
  20,000,263 ratings and 26,715 enriched movie rows. The candidate database is
  published only after successful validation, commit and checkpoint.
- The first retry with DuckDB 1.4.4 also failed at the final commit. Its task log
  gives the cause: the 4 GB DuckDB memory cap was full (3.7 GiB used), and it
  could not pin another 256 KiB block. This was not a container OOM kill.
- The next retry succeeded after disabling insertion-order preservation. All
  five Airflow tasks are green. The load record confirms DuckDB 1.4.4, a 4 GB
  memory limit, one thread, and all 20,000,263 ratings committed and published.

## Recovery changes

- Both dependency manifests now pin `duckdb==1.4.4`, a newer stable release with
  Python 3.11 Linux ARM64 and AMD64 wheels. This is an upgrade attempt, not a
  claim that this exact engine failure is fixed in that version.
- Airflow forwards the pipeline subprocess's stdout/stderr into task logs.
- The loader prints phases and saves version, resource settings and the last
  operation in `reports/quality/<run-id>-load-progress.json`.
- `resume_run` is nullable in the trigger form; blank means a fresh run.
- The loader's candidate-file publication and schema constraints are retained.
- The loader now disables DuckDB insertion-order preservation, as suggested by
  the engine's memory error. Rating batches are explicitly ordered by rowid, so
  this setting does not change the warehouse's row contents or batch order.

The updated setting was rebuilt and used in the successful retry.

## Preserved warehouse backup

The original published file was copied before preparing the engine upgrade:

`warehouse/backups/movielens-before-duckdb-upgrade-20261012.duckdb`

- Size: 3,994,824,704 bytes.
- Original engine: DuckDB 1.2.2.
- SHA-256:
  `3eb163f564894040325e26592f8e6eb32341174540ed0ec24092842720a71366`.
- Source and backup hashes matched. Adjacent JSON records the paths and hash.

Keep this backup while recovering. A newer engine may write a newer database
format, so retain the original file for returning to the earlier environment.
Raw MovieLens files, cached API responses and failed candidate files have not
been deleted.

## Activate after the failed run is idle

Close DuckDB UI and ensure no Airflow task is running. From the project folder:

```sh
unset DOCKER_DEFAULT_PLATFORM
docker compose build project
docker compose --profile airflow up -d --no-deps --force-recreate project airflow
docker compose exec -T airflow /usr/local/bin/python -c "import duckdb; print(duckdb.__version__)"
```

The version should be `1.4.4`. Both containers use the same rebuilt image,
avoiding different DuckDB versions against the shared warehouse file. No source
download or rating transformation is launched by these activation commands.

## Retry the three remaining tasks

In Airflow, open `movielens_pipeline`, select the run at **08:13:56 UTC**
(15:13:56 Bangkok time), and select `load`:

1. Click **Clear task**.
2. Select **Downstream**, leaving **Upstream**, **Past** and **Future** off.
3. Confirm the affected tasks are exactly `load`, `validate` and `olap` in that run.
4. Click **Clear** and enable auto-refresh.

This reuses the run's original staging and cached metadata. It does not fetch
TMDb again or rerun Spark. A new DAG run would require the resume option to
reuse that staging; clearing tasks within the existing run avoids that need.

Verified recovery: the saved staging data was reused; Spark and TMDb extraction
did not rerun. The completed run has 20,000,263 ratings, 138,493 users, 27,278
movies, and zero violations in all six integrity checks. The full run report is
`reports/runs/airflow-7ad6db2270f8de79ba22.json`; load progress is in
`reports/quality/airflow-7ad6db2270f8de79ba22-load-progress.json`. The updated
OLAP benchmark evidence is in `reports/results/olap.json` and `.csv`.

## Primary references

- [DuckDB crash troubleshooting](https://duckdb.org/docs/current/guides/troubleshooting/crashes)
- [DuckDB 1.4.4 release files](https://pypi.org/project/duckdb/1.4.4/)
