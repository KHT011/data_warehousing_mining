# MovieLens 20M warehouse

MovieLens + TMDB → PySpark ETL → Parquet → DuckDB warehouse → OLAP queries

## 0. Repository and Dataset preparation

Clone the repository

```sh
git clone https://github.com/KHT011/data_warehousing_mining.git
cd data_warehousing_mining
```

Download the dataset

```sh
curl -O https://files.grouplens.org/datasets/movielens/ml-20m.zip
```

## 1. Start the project

Use Docker Desktop with Linux containers and about 8 GB of memory. Run these commands from the project folder:

Docker automatically extracts the six CSVs from `ml-20m.zip` into `data/raw/` at startup, skips existing files, and fills in missing files. Without the ZIP, you can still run the synthetic smoke demo.

```sh
docker compose build
docker compose up -d
docker compose exec project python run_pipeline.py smoke
```

The smoke run uses synthetic MovieLens and cached synthetic TMDB data. It needs no API token and does not change the full warehouse. Dependencies are installed inside Docker; the initial build needs internet access.

## 2. Build the full warehouse

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

Open [localhost:8080](http://localhost:8080) and log in as **admin**. Get the password privately:

```sh
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt
```

Enable and trigger **movielens_pipeline**. Choose `smoke=true` for a demo or `smoke=false` for the full dataset. Keep `live=false` to run offline.

The five tasks are **extract → transform → load → validate → olap**.

## Useful commands

```sh
docker compose exec project bash                    # Explore the container
docker compose exec project python -m pytest -q     # Run tests
docker compose stop                                # Stop both services
docker compose start                               # Start them again
```

Containers stay running until stopped. Data remains in the project folder; Airflow state uses a Docker volume.
