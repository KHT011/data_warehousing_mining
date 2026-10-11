FROM python:3.11.11-slim-bookworm@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless libgomp1 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src SPARK_LOCAL_IP=127.0.0.1 OMP_NUM_THREADS=2
WORKDIR /app
COPY requirements.txt requirements.lock.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock.txt && pip check
RUN python -c "import duckdb; duckdb.connect().install_extension('ui')"
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
COPY requirements-airflow.txt ./
COPY airflow/constraints-3.11.txt ./airflow/constraints-3.11.txt
# Airflow has its own constrained environment, isolated from Spark and DuckDB.
RUN python -m venv /opt/airflow-venv && /opt/airflow-venv/bin/pip install --no-cache-dir -r requirements-airflow.txt -c airflow/constraints-3.11.txt && /opt/airflow-venv/bin/pip check
ENV AIRFLOW_HOME=/opt/airflow AIRFLOW__CORE__DAGS_FOLDER=/app/airflow/dags AIRFLOW__CORE__LOAD_EXAMPLES=False AIRFLOW__CORE__EXECUTOR=SequentialExecutor AIRFLOW__CORE__PARALLELISM=1 AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////opt/airflow/airflow.db AIRFLOW__WEBSERVER__WORKERS=1 AIRFLOW__CORE__DEFAULT_TIMEZONE=UTC AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=True AIRFLOW__WEBSERVER__EXPOSE_CONFIG=False
RUN ln -s /opt/airflow-venv/bin/airflow /usr/local/bin/airflow
COPY src ./src
COPY sql ./sql
COPY warehouse/*.sql ./warehouse/
COPY tests ./tests
COPY run_pipeline.py README.md ./
COPY notebooks ./notebooks
COPY airflow/dags ./airflow/dags
ENTRYPOINT ["python", "-m", "utils.container_runtime"]
CMD ["idle"]
