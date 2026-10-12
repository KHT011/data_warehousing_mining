# Progress-report preliminary mining and EDA

Status: Done

Scope: Current MovieLens/TMDb DuckDB project, not the older SQLite/Wikidata project.

Acceptance criteria:
- [x] Read the current published warehouse with a read-only connection and Docker mount.
- [x] Use every rating for EDA and chronological baseline partitions; fit clustering on every rating-active user.
- [x] Produce rating, activity and allocated-genre charts, feature definitions and preparation evidence.
- [x] Compare preliminary cluster counts and report silhouette, full-user Davies–Bouldin/Calinski–Harabasz, seed stability, sizes and profiles.
- [x] Evaluate global-average and movie-average predictions using training statistics only, with RMSE/MAE, chronological boundaries and cold-movie fallback counts.
- [x] Save an executed notebook, reproducibility manifest, charts, CSV tables and a report-ready section.
- [x] Distinguish the small silhouette metric sample from fitting: no rating or fitting-user subsample.
- [x] Record actual results and limitations; this work does not establish H3 model improvement.

Completion evidence:
- Completed Docker notebook run: 20261012T101412847806Z.
- All eight code cells executed with zero errors; all 20,000,263 ratings and 138,493 users reconciled.
- Stored clustering model reproduced every user assignment; all user genre shares sum to one.
- Independent NumPy accumulation across all 3,000,040 test events matched SQL baseline RMSE/MAE.
- EDA and composite charts were visually inspected; report section, metadata, feature definitions and CSVs saved.
- Selected k=2, silhouette 0.1020, seed ARI 0.4049: weak/initialization-sensitive separation.
- Test global RMSE/MAE 1.0177/0.7901; movie-average with fallback 0.9580/0.7298.
- Warehouse was read-only with unchanged count/sum summaries; final supervised H3 fitting remains future work.
