# MovieLens 20M warehouse

MovieLens + TMDB → PySpark ETL → Parquet → DuckDB warehouse → OLAP queries.
Airflow runs the warehouse pipeline. Preliminary EDA, user descriptors and
chronological rating baselines have a separate Docker mining service; the
older feature-model experiments remain inactive.

## 1. Start the project

Use Docker Desktop with Linux containers. Start with 8 GB allocated to Docker
for manual full-data runs and stop other heavy containers. The image selects
the build machine's native architecture, including Apple Silicon. If you
previously exported `DOCKER_DEFAULT_PLATFORM=linux/amd64`, unset it first.
Airflow is optional and starts only when explicitly enabled.

Run these commands from the project folder:

```sh
unset DOCKER_DEFAULT_PLATFORM
docker compose build
docker compose up -d
docker compose exec project python run_pipeline.py smoke
```

The smoke run uses synthetic MovieLens and cached synthetic TMDB data. It needs no API token and does not change the full warehouse. Dependencies are installed inside Docker; the initial build needs internet access.

The manual container is capped at 6 GB and 2 CPUs. Spark's default heap is 3 GB;
DuckDB's default engine limit is 4 GB with one query thread. These are separate stages with additional
memory overhead, not guarantees of total process usage. Configure the budgets
through `.env`; see [Docker resource configuration](DOCKER_RESOURCES.md).

**For an existing running collection, wait for its completion before rebuilding
or recreating containers.** The resource update takes effect after recreation.

## 2. Build the full warehouse

The dataset is excluded from Git. If `data/raw/` already contains the six MovieLens CSVs, skip extraction. Otherwise, obtain `ml-20m.zip`, place it in the project folder, and run in PowerShell:

```powershell
Expand-Archive -LiteralPath ./ml-20m.zip -DestinationPath ./data/raw
Move-Item -Path ./data/raw/ml-20m/* -Destination ./data/raw/
```

Then run:

```sh
docker compose exec project python run_pipeline.py
```

This audits the source, transforms it with Spark, loads DuckDB, checks data quality and benchmarks five OLAP queries. Allow several gigabytes of free disk space for data, staging and a temporary warehouse copy. TMDB uses cached data only by default.

## 3. Explore with DuckDB UI

```sh
docker compose exec project python run_pipeline.py ui
```

Open [localhost:4213](http://localhost:4213), create a notebook, and select **movielens** in the SQL cell's database dropdown. Paste queries from [sql/olap_queries.sql](sql/olap_queries.sql) or [sql/analysis_queries.sql](sql/analysis_queries.sql).

The UI needs internet for frontend assets. Press **Ctrl+C** before running another load or refresh. If the UI is running in the background, close it with `docker compose restart project`.

## 4. Run through Airflow

Enable the optional Airflow service:

```sh
docker compose --profile airflow up -d
```

Airflow runs Spark/DuckDB jobs inside its own container, so its cap is 7 GB and
3 CPUs. Start with 12 GB allocated to Docker for full runs through Airflow if
your computer has enough RAM; leave memory for macOS and other applications.
The default manual container remains idle while Airflow runs the workflow.

Open [localhost:8080](http://localhost:8080), or your configured `AIRFLOW_PORT`,
and log in as **admin**. Get the password privately:

```sh
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt
```

Enable and trigger **movielens_pipeline**. Choose `smoke=true` for a demo or `smoke=false` for the full dataset. Keep `live=false` to run offline.

The five tasks are **extract → transform → load → validate → olap**.

For a fresh run, leave `resume_run` blank. It is an optional recovery identifier,
not a field where you should enter the word `empty`.

The load recovery update pins DuckDB **1.4.4**, forwards engine output into
Airflow's task logs, and disables insertion-order preservation during loading
to reduce memory use. The first full-data retry reached the 4 GB DuckDB memory
cap at commit; the next retry succeeded with all five Airflow tasks green and
all 20,000,263 ratings published. See [Load recovery](LOAD_RECOVERY.md) for the
run evidence.

## 5. Preliminary mining and EDA

Use the published warehouse after its ETL has finished:

```sh
docker compose --profile mining build mining
docker compose --profile mining run --rm --no-deps mining
```

The mining image uses the existing `movielens-project:local` image as its base;
build the project image first on a new machine. It mounts the warehouse read-only
and executes [the preliminary notebook](notebooks/05_mining_preliminary.ipynb).
EDA and chronological global/movie-average baselines use every rating event.
User descriptors include every rating-active user. The milestone notebook
does not fit clusters; the earlier executed experiment is preserved in
`notebooks/archive/`.

Numerical results are saved under `reports/results/mining_preliminary/`.
The simple report section and its charts are under `reports/results/mining_milestone/`. Feature/assignment/model artifacts are
under `data/processed/mining_preliminary/`. See [the mining run guide](MINING_PRELIMINARY.md).

## Useful commands

```sh
docker compose exec project bash                    # Explore the container
docker compose exec project python -m pytest -q     # Run tests
docker compose --profile airflow stop              # Stop project and optional Airflow
docker compose up -d project                        # Start the manual service
docker compose --profile airflow up -d              # Start with Airflow
```

Containers stay running until stopped. Data remains in the project folder; Airflow state uses a Docker volume.

See [the detailed guide](docs/README.md), [warehouse schema](docs/schema.md) and [measured results](reports/results/IMPLEMENTATION.md). Git includes source, documentation and selected small results; datasets, warehouse databases, credentials, archives and runtime output stay local. Copy `.env.example` to `.env` only when configuring TMDB or a different Airflow port; never commit `.env`.
