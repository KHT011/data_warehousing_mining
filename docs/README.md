# MovieLens 20M warehouse

**MovieLens CSV + TMDB → PySpark ETL → Parquet → DuckDB star schema → OLAP → DuckDB UI**

A local academic project. Airflow automates the same five stages as the Python runner. Mining source and notebooks are retained but inactive.

## Run

Start the installed Docker Desktop Linux engine. From this project directory:

```sh
docker compose build
docker compose up -d
docker compose exec project python run_pipeline.py smoke
```

The smoke command uses synthetic data in `data/smoke/` and `reports/smoke/`; it never changes the full warehouse or calls TMDB. No local Python, Java or package installation is needed.

To process **all MovieLens ratings**, using cached TMDB metadata where available:

```sh
docker compose exec project python run_pipeline.py
```

This performs extraction/audit → Spark transformation → warehouse loading → quality validation → five query benchmarks and EDA figures. Defaults use Spark 4 GB, then DuckDB 6 GB in separate processes; allocate approximately 8 GB to Docker and leave space for a temporary warehouse copy and staging. Configuration is in `src/utils/config.py`.


## Present with DuckDB UI

After the pipeline finishes:

```sh
docker compose exec project python run_pipeline.py ui
```

Open **http://localhost:4213**. Create an empty notebook and select **movielens** in the SQL cell's database dropdown (the initial default is `memory`). Paste individual statements from `sql/olap_queries.sql` and click Run. Each query runs independently; change the commented year, genre and support literals to explore. `sql/analysis_queries.sql` provides counts, dimension joins and Type 3 history inspection.

The official UI downloads its frontend assets from the internet. Its extension is installed in the Docker image. A small Python TCP helper exposes it through the existing project container; Docker Desktop settings stay unchanged. The warehouse is attached read-only, while UI scratch work uses an in-memory database.

Press **Ctrl+C** in the UI terminal before loading or refreshing data. The UI holds the pipeline/warehouse locks; another load exits with an explanatory message. The project container remains running when the UI closes.

If the UI was started in the background, `docker compose restart project` closes it and releases the lock.

## Automate with Airflow

Open **http://localhost:8080**, username `admin`. Retrieve the generated password privately:

```sh
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt
```

Enable and trigger **movielens_pipeline**:

```text
extract → transform → load → validate → olap
```

Choose `smoke=true` for the synthetic demonstration; use `smoke=false` for the full dataset. `live=false` is the default. Runs are manual and serialized. The DAG passes arguments to the same runner, with no datasets in XCom. Airflow uses its own constrained Python environment, SQLite and SequentialExecutor inside the existing image. Its state persists in a named Docker volume.

## Other commands

```sh
docker compose exec project python run_pipeline.py olap
docker compose exec project python run_pipeline.py refresh
docker compose exec project python run_pipeline.py run --resume-run RECORDED_RUN_ID
docker compose exec project python -m pytest -q
docker compose exec project bash
docker compose stop
```

`olap` benchmarks the existing warehouse. `refresh` updates only movie metadata. `--resume-run` reuses reconciled Parquet and its original staged metadata after checking source hashes. Recovery runs are offline; use `refresh --live` afterward to fetch newer metadata. Both services use `restart: unless-stopped`; `docker compose start` resumes them. `docker compose down` removes containers while retaining bind-mounted project data and the Airflow volume.

## Data and correctness

The supplied `ml-20m.zip` has been extracted. The six original CSVs and release README are in `data/raw/`. Genome files are retained and audited; the initial warehouse uses ratings, movies, links and tags.

Raw files are unchanged. Spark validates IDs, timestamps, rating ranges and movie references; quarantines rejected rows; removes exact duplicates; and rejects conflicting event identities. Recorded counts reconcile raw = retained + duplicate + rejected rows.

DuckDB contains `FactRatings`, `DimUser`, `DimMovie`, `DimDate`, `DimGenre`, `BridgeMovieGenre` and `ETLRun`. The rating-event hash is a degenerate dimension. Genre allocation weights sum to one; genre overlap is explicitly identified in OLAP queries. See [schema and ERD](schema.md) and [bus matrix](bus_matrix.md).

Loads preserve surrogate keys and existing metadata. A candidate database is validated before replacing the published warehouse. Type 3 history retains current/previous runtime and original language; unchanged or failed API fetches do not shift or erase history.

TMDB remains offline unless you explicitly opt in. Once network and a private token are available, put `TMDB_TOKEN` in the ignored `.env` file, recreate services with `docker compose up -d`, then run:

```sh
docker compose exec project python run_pipeline.py refresh --live --tmdb-limit 500
```

Extraction uses resumable snapshots, language-aware caching, bounded retries, throttling and bounded stale refreshes. It does not claim global change-feed completeness. Snapshots and state are under `data/raw/tmdb/`. Full loads stage API metadata through Spark/Parquet; metadata-only refreshes reuse the same Type 3 update logic.

## Files and results

```text
run_pipeline.py                 one entry point
src/etl/                        extract, transform, load, quality and smoke fixture
src/utils/                      config, locking, UI and container startup
src/pipeline.py                 shared five-stage flow and recovery
src/analytics.py                five benchmarks and EDA
src/mining/                     active preliminary workflow; older models inactive
warehouse/                      schema.sql, load_warehouse.sql, movielens.duckdb
sql/                            OLAP, inspection and integrity SQL
airflow/dags/                   one warehouse DAG
notebooks/                      audit, EDA; inactive mining notebooks
data/raw/                       original CSVs and TMDB snapshots
data/staging/                   current *.parquet/ datasets and manifest.json
reports/results/                measured quality, timings and verification
reports/figures/                EDA figures and supporting data
tests/                          warehouse contracts; inactive mining tests in mining/
```

Spark's `.parquet` paths are directories containing part files. An unfinished transformation remains under `data/staging/.work/` for recovery. Successful publication keeps one current staging dataset. Synthetic outputs are labeled separately.

`reports/results/warehouse.json` records the latest full workflow; `olap.json` and `olap.csv` contain warm-up plus five measured repetitions for fact and preaggregate queries, with result-equivalence checks. Historical results are preserved; they are not substituted for new verification. See `reports/results/IMPLEMENTATION.md` for this refactor's measured results and cleanup.

The executed progress notebook is `notebooks/05_mining_preliminary.ipynb`. The optional Docker `mining` profile runs it, reconciles every user assignment and test-rating error, and creates report sections/charts. See `MINING_PRELIMINARY.md` in the project root. Older feature-model notebooks/modules remain inactive and use a different experimental protocol; they are not the full-data progress-report results.

Original assignment documents and implementation guidance remain in `docs/`. Historical evidence is in `reports/history.zip`; prior operational plans and reviews are in `docs/history.zip`. Both archives were checked against the original files' SHA-256 hashes before removing duplicates. This README describes the current workflow. Raw data, database files, credentials and generated outputs are excluded from the image and version control.
