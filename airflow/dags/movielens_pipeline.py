"""Raw/API → Spark → Parquet → DuckDB → OLAP. Manual/offline by default."""
from datetime import datetime, timedelta, timezone
from airflow import DAG
from airflow.models.param import Param
from airflow.operators.python import PythonOperator
from orchestration import run_step


def execute(step, **context):
    run_step(step, dict(context['params']), run_id=context['dag_run'].run_id)


with DAG('movielens_pipeline', start_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
         schedule=None, catchup=False, max_active_runs=1, max_active_tasks=1,
         default_args={'retries': 1, 'retry_delay': timedelta(seconds=15)},
         params={
             'smoke': Param(False, type='boolean', description='Isolated synthetic offline demo'),
             'live': Param(False, type='boolean', description='Explicit TMDB; network and token required'),
             'tmdb_limit': Param(500, type=['integer', 'string'], minimum=1, pattern=r'^(all|[1-9][0-9]*)$'),
             'resume_run': Param(None, type=['null', 'string'],
                                 description='Optional recorded staging run ID; leave blank for a fresh run'),
         }, tags=['academic', 'warehouse']) as dag:
    previous = None
    for step in ('extract', 'transform', 'load', 'validate', 'olap'):
        task = PythonOperator(task_id=step, python_callable=execute,
                              op_kwargs={'step': step}, do_xcom_push=False)
        if previous is not None:
            previous >> task
        previous = task
