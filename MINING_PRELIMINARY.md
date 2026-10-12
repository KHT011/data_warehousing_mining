# Preliminary mining for the progress report

The milestone notebook uses the current MovieLens/TMDb DuckDB warehouse.
Its scope is data preparation, EDA, user descriptors and two rating baselines.
It does not fit a clustering or supervised prediction model.

## Run with Docker

Finish warehouse ETL or metadata updates first. The mining service mounts the
warehouse read-only. On a new machine, build the `project` image before `mining`.

```sh
docker compose --profile mining build mining
docker compose --profile mining run --rm --no-deps mining
```

The existing one-off service executes notebook 05, checks its saved results and
creates the simple report section. It has two CPUs and a 4 GiB cap; DuckDB uses
one query thread and a 2 GB engine memory budget.

## Notebook order

1. Read the cleaned warehouse and show its size/date range.
2. Plot rating scores, monthly activity, user/movie activity and weighted genres.
3. Prepare one row per rating-active user: rating count, average score, score
   variation, high-score share, activity span and 20 genre shares. No scaling or
   clustering is applied in this milestone notebook.
4. Split all events by UTC time (about 70/15/15), preserving timestamp ties.
5. Compare training-only global and movie averages on the same later events.
6. Save the outputs and compare warehouse count/sum/date summaries before/after.

All 20,000,263 ratings are used. User descriptors summarize full history and
must not be reused directly for H3 prediction. The movie baseline uses the
training global mean for movies with no training ratings. Current TMDb scores,
popularity, tags and genome features are excluded from these baselines.

## Outputs

- `notebooks/05_mining_preliminary.ipynb`: runnable milestone notebook.
- `reports/results/mining_preliminary/<run-id>/`: EDA, feature definitions,
  split counts, validation/test baseline metrics and run provenance.
- `data/processed/mining_preliminary/<run-id>/user_features.parquet`: all user
  descriptors, including the original-unit columns shown in the notebook.
- `reports/results/mining_milestone/REPORT_SECTION.md`: simple report section.
- `reports/results/mining_milestone/<run-id>/`: report section and two charts.
- `reports/results/mining_preliminary/verification.json`: results of the existing
  reconciliation workflow after a successful Docker run.

H2 and H3 remain the original research questions. The milestone prepares H2
inputs and establishes H3 prediction references, without claiming either
hypothesis has been confirmed.

## Preserved experiment and measured evidence

The earlier executed clustering notebook is preserved at
`notebooks/archive/05_mining_clustering_experiment_20261012.ipynb`.
Its measured run folders and model artifacts remain unchanged.

The current report uses measured run `20261012T105513014787Z` from 12 October:
20,000,263 ratings, 138,493 users and 26,744 rated movies. Test RMSE/MAE were
1.0177/0.7901 for the global average and 0.9580/0.7298 for the movie average with
fallback. These results were previously checked against all test events.

Notebook 05 was simplified on 13 October. Its code outputs were cleared to
avoid presenting the old clustering execution as a run of the revised notebook.
The revised notebook has not been executed yet. A future Docker run generates
fresh outputs and provenance; the report revision reuses saved measurements.
