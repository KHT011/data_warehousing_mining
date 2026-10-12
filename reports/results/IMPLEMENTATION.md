# Simplification verification — 11 October 2026

The active flow is MovieLens CSV/cached TMDB → Spark → Parquet → DuckDB → OLAP. Airflow is integrated; mining source, leakage controls and historical results are retained inactive. No local software was installed and no live TMDB request was made.

## Measured full-data run

- Full pipeline and signature comparison: **760.67 seconds**.
- Ratings: **20,000,263**; warehouse users: **138,493**; movies: **27,278**.
- All six integrity checks: zero violations. Raw/retained ratings reconcile; full-source audit is retained in `reports/quality/source_audit.json`.
- Before/after count, rating-sum and hash signatures match for facts, user/movie key mappings and movie metadata. Hash signatures are an operational comparison, not a mathematical proof of every row's equality.
- This was an uninterrupted offline full reload. TMDB coverage was 0 payloads; unenriched metadata was preserved honestly.
- Timings by stage: extract 38.91s, transform 321.44s, load 337.66s, validate 1.53s, olap 52.78s.

## Airflow full-data recovery — 12 October 2026

- Airflow run `manual__2026-10-12T08:13:56+00:00` completed all five tasks successfully after retrying only `load`, `validate`, and `olap`.
- DuckDB **1.4.4**, one thread, 4 GB engine memory cap, Linux ARM64 Docker container. Loading used 500,000-rating batches and disabled insertion-order preservation after the first 1.4.4 attempt reached its memory cap at commit.
- Final warehouse: **20,000,263 ratings**, **138,493 users**, **27,278 movies**; all six integrity checks returned zero violations.
- The run was offline and reused cached metadata for **26,698 movies**; recovery did not repeat the TMDb fetch or Spark transformation.
- Airflow stage timings: extract 32.40s, transform 120.80s, load 898.84s, validate 1.16s, OLAP 85.41s. Load includes the successful retry and candidate publication.
- Full run details are in `reports/runs/airflow-7ad6db2270f8de79ba22.json`; load progress is in `reports/quality/airflow-7ad6db2270f8de79ba22-load-progress.json`.

## OLAP benchmarks

One warm-up followed by five measured warm repetitions per query/variant. Fact and monthly-preaggregate results agree within floating-point tolerance. These are local measured results; no cold-cache claim is made. The following are regenerated results from the 12 October Airflow run, using one DuckDB thread.

| Query | Fact median (s) | Preaggregate median (s) | Results |
|---|---:|---:|---|
| Q1 | 1.0049 | 0.0713 | agree |
| Q2 | 4.4658 | 0.2231 | agree |
| Q3 | 1.0861 | 0.0721 | agree |
| Q4 | 0.1202 | 0.0125 | agree |
| Q5 | 3.9713 | 0.3469 | agree |

Detailed timings, results and EXPLAIN ANALYZE evidence are in `olap.json`, `olap.csv`, query-result CSVs and analysis text files.

## Acceptance checks

- **29 active tests passed in 202.82 seconds**, covering reconciliation, rejected input, broken references, stable keys, Type 3 history, API retries/cache, lock release, staged-source fingerprints and interrupted publication.
- Airflow's real scheduler completed all five synthetic tasks successfully in **53.67 seconds**; no task retries were needed. `airflow.json` records task durations.
- The official DuckDB UI was verified in the browser against the full warehouse: **20,000,263 ratings**, **138,493 rating users**, **26,744 rated movies**, and **331 roll-up rows**.
- UI attaches the warehouse read-only. An open UI session prevented a refresh before processing, with an instruction to close the UI.
- The synthetic smoke path includes a cached synthetic TMDB response through Spark/Parquet. It is kept separate from full-data evidence.
- The rebuilt final image completed all five offline smoke stages: 1,800 retained ratings, one staged synthetic TMDB movie and zero integrity violations. The isolated A/B/C Type 3 demo kept runtime 90 unchanged on repeat, then stored current 95 / previous 90 while preserving facts and keys. See `final-validation.json` and `reports/smoke/results/scd3_demo.json`.
- A subsequent offline full-warehouse metadata refresh succeeded with 20,000,263 ratings and zero integrity violations. Both containers stayed running; Airflow was healthy with no DAG import errors.
- An independent review identified load-publication retry and resumed-metadata risks. Publication now has a recovery journal and recognizes already committed loads. Recovery retains original staged metadata and requires a separate explicit live refresh for newer metadata.
- The full 20M run preceded those narrow recovery fixes; the final test suite covers them, and the final Docker smoke run checks their integration. The 20M load was not repeated after those fixes.

## Cleanup and preservation

- Removed **2.424 GiB** of generated artifacts: obsolete staging, failed candidate, old smoke data and test temporary directories.
- Measured folders totaled **8.680 GiB immediately before cleanup**, then **6.206 GiB immediately after cleanup**. The before measurement includes both the newly built staging and its obsolete predecessor; it is not the project's original size. A small final smoke dataset is recreated afterward.
- Historical reports/results were compressed into `reports/history.zip`; previous operational documents into `docs/history.zip`. Every archived entry was verified against its source SHA-256 before duplicate files were removed.
- Original CSVs, ZIP release, PDFs, mining source/notebooks, schema and recorded results were preserved. Original source is additionally recoverable from `before-simplification-source.zip`.
- Full reloads now create fresh candidate facts while copying persistent dimension keys/history and ETL provenance, avoiding duplicated obsolete fact pages. Unknown extra warehouse tables cause a clear failure instead of being dropped.
- Docker images/build caches were not pruned. Runtime data is excluded from the image. The persistent project and Airflow services remain available until stopped.

The full warehouse and Parquet staging naturally occupy several gigabytes. The README is the current run guide; archived plans document the previous structure.
