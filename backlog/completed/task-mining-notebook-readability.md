# Beginner-readable preliminary mining notebook

Status: Done

Scope: Improve the presentation of `notebooks/05_mining_preliminary.ipynb` for a beginner, preserving the current experiment and its full-data scope.

Acceptance criteria:
- [x] Explain EDA, user features, clustering, baseline predictions, chronological splits and error metrics beside the corresponding steps.
- [x] Replace repetitive/raw displays with focused summaries, readable column labels and existing charts.
- [x] Preserve all analysis calls, saved detailed metrics, read-only warehouse access and the H2/H3 limitations.
- [x] Explain why this combined notebook exists alongside notebooks 01–04.
- [x] Validate the notebook and execute all code cells; compare substantive results against the previous run.

Changes:
- Added a reading order, plain-language feature/metric definitions and a short explanation of notebook roles.
- Removed repeated EDA tables, the raw 25-feature list, the descriptive-statistics dump and the wide 29-column cluster profile display.
- Focused visible results on a five-user preview, cluster comparison/behavior and test baseline errors. Detailed metrics and diagnostics are still saved by the unchanged analysis functions.
- Retained all six charts and explicit limits: weak/unstable clusters require careful interpretation, supervised H3 improvement is untested, and tags/genome are absent.

Verification on 12 October 2026:
- Docker mining bundle completed run `20261012T105513014787Z`; all eight code cells executed without errors.
- Checked notebook JSON, compiled all code cells and inspected all six displayed tables for compact, complete columns.
- EDA counts/averages, feature list, cluster profiles/quality and chronological splits matched previous run `20261012T101412847806Z`; baseline metrics matched within 1e-10 numerical tolerance. Timing and run provenance naturally changed.
- Bundle verification reconciled all 20,000,263 ratings and 138,493 user assignments; saved model reproduced every assignment and all user genre shares summed to one.
- Independent error accumulation checked all 3,000,040 test events and matched SQL baseline scores. Read-only warehouse count/sum summaries stayed unchanged.
- Numerical methods, model parameters, warehouse tables and notebooks 01–04 were not edited. No new hypotheses or supervised-model results were claimed.
