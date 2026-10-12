# Docker resource configuration

## What changed

- Java is resolved from the installed binary into `/opt/java` during the image
  build. The pinned Python base image provides both ARM64 and AMD64 manifests.
  No platform is forced in Compose; native builds can be used on Apple Silicon
  and Intel/AMD computers.
- Compose applies CPU and memory caps to each service. The application reads
  Spark and DuckDB budgets from the environment and records its effective
  configuration with pipeline runs.
- Airflow belongs to the `airflow` profile. A plain `docker compose up -d`
  starts the manual project service. Explicitly enable Airflow when needed.
- Existing bind-mounted datasets, API responses, warehouse files and the
  Airflow state volume keep their current locations.

The ARM64 image has been built and activated. `uname -m` reported `aarch64`
and Docker reported the manual container's 6 GiB cap. The first native Airflow
full run completed extraction and transformation, then the load aborted inside
DuckDB 1.2.2 with an internal null-pointer exception. Its native trace reaches
index vacuum during commit rollback. The Airflow container recorded no OOM
kills; this does not rule out an engine-memory failure preceding the abort.
The published warehouse still had 20,000,263 ratings and 26,715 enriched movie
rows after the failure.

The recovery settings are now 4 GB and one DuckDB query thread. That retry
also aborted on DuckDB 1.2.2, with no container OOM kills. The source now pins
DuckDB 1.4.4 and adds load-phase logging; activation and recovery remain pending.
See [Load recovery](LOAD_RECOVERY.md). Existing benchmark timings describe the
previous runtime and need new measurements before claiming an improvement.

## The three memory budgets

1. **Docker Desktop VM:** the shared RAM available to all Linux containers.
2. **Container cap:** a ceiling for everything inside one container.
3. **Engine budget:** Spark's Java heap or DuckDB's managed-memory limit.

Engine budgets leave space for native allocations, Python, Java overhead,
Airflow processes and buffers. Neither engine setting limits all memory used
by its process. Container caps also do not reserve RAM from the shared VM.

## Defaults

| Setting | Default | Purpose |
| --- | --- | --- |
| `PROJECT_CPUS` | `2.0` | Manual container CPU cap |
| `PROJECT_MEMORY_LIMIT` | `6g` | Manual container RAM cap |
| `AIRFLOW_CPUS` | `3.0` | Airflow container CPU cap, including pipeline jobs |
| `AIRFLOW_MEMORY_LIMIT` | `7g` | Airflow container RAM cap, including pipeline jobs |
| `SPARK_CORES` | `2` | Local Spark worker threads |
| `SPARK_SHUFFLE_PARTITIONS` | `8` | Spark shuffle partitions |
| `SPARK_DRIVER_MEMORY` | `3g` | Spark Java heap |
| `DUCKDB_THREADS` | `1` | DuckDB worker threads |
| `DUCKDB_MEMORY_LIMIT` | `4GB` | DuckDB managed-memory budget |

Spark and DuckDB stages run sequentially in this pipeline. The same engine
settings apply to manual and Airflow execution. Keep worker counts within
their container CPU allowance and engine budgets below their container RAM cap.
Resource environment values take precedence over a custom YAML config.

In Docker Desktop Settings → Resources, start with:

- **Manual full load:** 8 GB for Docker; stop Airflow and other heavy projects.
- **Full load through Airflow:** 12 GB for Docker if host RAM permits. On a
  16 GB host, leave at least 4 GB for macOS and applications, and reduce other
  workloads. These are starting budgets, not measured minimum requirements.
- **API-only refresh:** the command uses Python and DuckDB; it does not start
  Spark. Airflow can remain stopped when launching it from Terminal.

Docker Desktop settings affect other running Docker projects and may restart
the VM. Change them only after active work has finished.

## Apply after the current collection finishes

Wait for the live refresh completion message and `Exit code: 0`. If it fails,
keep the error output and saved responses for diagnosis before applying changes.
Close DuckDB UI with Ctrl+C and finish any running Airflow task.

From this project folder:

```sh
docker compose --profile airflow stop
unset DOCKER_DEFAULT_PLATFORM
docker compose config --quiet
docker compose build project
docker compose up -d project
```

The build may download architecture-specific layers and dependencies. It does
not run the ETL. Recreating the container applies the new limits and application
settings. This procedure preserves the persisted source and warehouse data.

Inspect the running architecture and actual Docker caps:

```sh
docker compose exec -T project uname -m
docker inspect --format 'memory_bytes={{.HostConfig.Memory}} cpu_nanoseconds={{.HostConfig.NanoCpus}}' "$(docker compose ps -q project)"
docker stats --no-stream
```

An Apple Silicon native build should report `aarch64`. An Intel/AMD native build
should report `x86_64`. The default project memory cap is 6 GiB and CPU allowance
is 2 CPUs. If the Mac still reports `x86_64`, check shell platform overrides and
confirm the rebuilt image was used when the container was recreated.

To enable Airflow later:

```sh
docker compose --profile airflow up -d
```

Use the port configured by `AIRFLOW_PORT` in your private `.env`. During a full
manual run, keep Airflow stopped. The shared pipeline lock prevents concurrent
writers, but other running services still consume memory.

## Customize without replacing credentials

Keep the existing private `.env` file and its `TMDB_TOKEN`/`AIRFLOW_PORT` values.
The new resource keys are optional; omitted keys use the defaults above.
Add only keys you intend to change, for example:

```dotenv
PROJECT_MEMORY_LIMIT=6g
PROJECT_CPUS=2.0
SPARK_DRIVER_MEMORY=3g
DUCKDB_THREADS=1
DUCKDB_MEMORY_LIMIT=4GB
```

Spark heap sizes accept positive integer `m` or `g` units. DuckDB limits accept
positive integer `MB`, `GB`, `MiB` or `GiB` units. Thread and partition counts
must be positive integers. Invalid application resource values fail with a
clear configuration error.

After changing `.env`, finish active jobs before recreating the service:

```sh
docker compose up -d --no-deps --force-recreate project
```

## Recover the failed Airflow load

The failed run is `manual__2026-10-12T08:13:56+00:00`; its prepared staging
identifier is `airflow-7ad6db2270f8de79ba22`. Extraction and transformation
succeeded, so their outputs can be reused within that same DAG run.

If the private `.env` already overrides `DUCKDB_MEMORY_LIMIT` or
`DUCKDB_THREADS`, update only those keys to `4GB` and `1`. Keep credentials and
the configured port. Otherwise, Compose supplies the new defaults.

Once no pipeline task is active and DuckDB UI is closed:

```sh
docker compose --profile airflow up -d --no-deps --force-recreate airflow
```

Wait for Airflow to initialize, open the failed run, select `load`, and clear
that task with its downstream tasks (`validate`, `olap`). Leave upstream tasks
unchecked to reuse the prepared data. This schedules the actual load retry;
it does not fetch TMDb again. Keep the previous run's logs as failure evidence.

The resource overrides were applied without rebuilding, but they did not resolve
the native crash. The DuckDB upgrade and log changes now require a rebuild;
follow [Load recovery](LOAD_RECOVERY.md) before retrying again. The original
extraction-time config records the earlier 3 GB / 2-thread budget. The updated
loader writes the actual DuckDB version, load budget and last operation to
`reports/quality/<run-id>-load-progress.json` so recovered results can identify
the effective load settings.

If a job loses its Java connection again, inspect current memory and OOM events:

```sh
docker compose exec -T project cat /sys/fs/cgroup/memory.events
docker stats --no-stream
```

`oom_kill` is cumulative for that container. An increase during a failed run
indicates a memory-related process kill. Recreating a container resets its
counter, so record it before and after a run. Raising a container cap alone
does not increase Docker Desktop's shared RAM.

## References

- [Docker Compose service resource settings](https://docs.docker.com/reference/compose-file/services/)
- [Docker Desktop resource settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/)
