# Preliminary mining for the progress report

This workflow is for the current MovieLens/TMDb DuckDB warehouse. It does not
reuse the older SQLite/Wikidata experiment's numerical results.

## Run with Docker

Finish ETL or metadata updates before running. The warehouse is mounted
read-only; outputs go to reports, derived data and the notebook. Existing
Airflow/project containers need not be recreated for this mining workflow.

```sh
docker compose --profile mining build mining
docker compose --profile mining run --rm --no-deps mining
```

On a new machine, build `project` before building `mining`. The extra image
adds scikit-learn and notebook execution dependencies using the project's
locked scientific libraries. The one-off mining service has two CPUs and
a 4 GiB cap; SQL uses one thread and a 2 GB managed-memory budget.

## Scope and preparation

- EDA uses every `FactRatings` row and distinguishes rated movies from the
  full metadata catalog. It profiles ratings, UTC months, user/movie activity
  and fractional genre exposure.
- H2 summarizes every rating-active user. Descriptors are log rating count,
  mean and population standard deviation, score >=4 share, log activity span,
  and weighted genre shares. StandardScaler normalizes the descriptors.
  There is no event or fitting-user sample.
- MiniBatchKMeans compares k=2,3,4,5 using seed 42 and seed 43 for stability.
  Silhouette uses the same seeded 2,000-user metric subset because exact
  pairwise evaluation is expensive. Davies–Bouldin, Calinski–Harabasz and ARI
  use all users. Metric sampling is separate from model fitting.
- H3 partitions all ratings by 70th and 85th percentile UTC timestamps, with
  tied timestamps kept together. Global/movie means use training events only.
  Unseen movies use the training global mean. Validation and test RMSE/MAE,
  test seen/unseen-movie errors and support counts are saved.
- Current TMDb rating/popularity/vote values are excluded from historic rating
  prediction. Tags/genome are absent from this project's active fact schema.
  H2 full-history descriptors are not predictive H3 features.

## Outputs

- `notebooks/05_mining_preliminary.ipynb`: executed code, tables and charts.
- `reports/results/mining_preliminary/latest.json`: completed run manifest.
- `reports/results/mining_preliminary/REPORT_SECTION_SHORT.md`: concise section
  with two composite figures for the progress report. `REPORT_SECTION.md`
  contains the detailed version with all six individual charts.
- `reports/results/mining_preliminary/verification.json`: checks on every user
  assignment and independent NumPy verification of every test-rating error.
- `reports/results/mining_preliminary/progress.json`: most recent phase.
- Per-run report folder: EDA/cluster/baseline JSON, CSV tables, six PNG figures,
  feature definitions, a report section, parameters, versions and code hash.
- `data/processed/mining_preliminary/<run-id>/`: every user's features/cluster
  assignment and the scaler/clustering model. These derived files remain local.

Use the saved numerical results rather than assumed archetypes. Silhouette
near zero means overlapping groups. Baseline performance is a reference for
later supervised models; it does not prove H3 model improvement. No final
model tuning or hypothesis conclusion is part of this preliminary workflow.

## Measured completion — 12 October 2026

Run `20261012T101412847806Z` completed successfully against warehouse ETL run
`airflow-7ad6db2270f8de79ba22`. All eight notebook code cells executed without
errors. Counts: 20,000,263 ratings, 138,493 users, 26,744 rated movies.

H2 selected k=2 among four candidates; cluster sizes are 78,148 and 60,345.
Sampled silhouette is 0.1020 and seed-stability ARI 0.4049, so the report
describes weak separation and initialization sensitivity. These groups do not
establish strong user archetypes.

H3 used 14,000,184 training, 3,000,039 validation and 3,000,040 test events.
Test RMSE/MAE: global mean 1.0177/0.7901; movie mean with fallback
0.9580/0.7298. Unseen movies require global fallback for 834,011 test events.
Independent NumPy calculations over all test events matched the SQL metrics;
the stored model reproduced every user assignment. The read-only warehouse
count/sum summary was unchanged. The integrated run reproduced the earlier
preliminary numerical results.
