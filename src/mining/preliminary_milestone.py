"""Simple progress-report material from measured EDA and rating baselines."""
from pathlib import Path
import json
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mining.preliminary import COLORS, figure, save_json


def build_report(result):
    source = Path(result['results_directory'])
    root = Path('reports/results/mining_milestone')
    out = root / result['run_id']
    out.mkdir(parents=True, exist_ok=True)
    class Context:
        pass
    ctx = Context()
    ctx.out = out
    ratings = pd.read_csv(source / 'rating_distribution.csv')
    activity = pd.read_csv(source / 'monthly_activity.csv', parse_dates=['rating_month'])
    genres = pd.read_csv(source / 'genre_activity.csv')
    users = pd.read_parquet(Path(result['derived_data_directory']) / 'user_features.parquet')
    fig, axes = plt.subplots(2, 2, figsize=(10, 6))
    axes[0, 0].bar(ratings.rating.astype(str), ratings.rating_count / 1e6, color=COLORS[0])
    axes[0, 0].set(xlabel='Rating score', ylabel='Ratings (millions)', title='(a) Rating distribution')
    axes[0, 1].plot(activity.rating_month, activity.rating_count / 1e6, color=COLORS[0])
    axes[0, 1].set(xlabel='Rating month (UTC)', ylabel='Ratings (millions)', title='(b) Rating activity over time')
    axes[1, 0].hist(users.rating_count, bins=np.geomspace(users.rating_count.min(), users.rating_count.max()+1, 35), color=COLORS[0])
    axes[1, 0].set(xscale='log', xlabel='Ratings per user (log scale)', ylabel='Users', title='(c) User activity')
    top = genres.head(8).iloc[::-1]
    axes[1, 1].barh(top.genre_name, top.allocated_ratings / 1e6, color=COLORS[0])
    axes[1, 1].set(xlabel='Allocated ratings (millions)', title='(d) Eight largest genre exposures')
    figure(ctx, 'eda_overview.png', fig)
    shutil.copyfile(source / 'h3_baseline_errors.png', out / 'baseline_errors.png')
    e = result['eda']
    b = result['baselines']
    splits = {v['split']:v['ratings'] for v in b['splits']}
    test = {v['model']:v for v in b['metrics'] if v['split']=='test'}
    text = f'''# Data mining preliminary

## Data preparation and EDA

We analyzed all {e['ratings']:,} cleaned ratings from {e['rating_users']:,} users and {e['rated_movies']:,} rated movies. The warehouse was read-only. MovieLens genres were joined through the genre bridge; a rating for a two-genre movie contributes 0.5 to each genre.

The overall mean rating was {e['mean_rating']:.2f}/5, and 4.0 was the most common score. The median user submitted {e['user_activity_quantiles']['0.5']:.0f} ratings. Genre counts describe exposure among rated movies, not proof that users like or watched every movie.

![EDA: scores, time, user activity and genre exposure.](eda_overview.png)

## Prepared features and strategy

One row describes one user. Prepared descriptors are rating count, mean rating, rating standard deviation, share of ratings at least 4, activity span in days and 20 weighted genre shares. No clustering model is fitted in this milestone notebook.

H2 will use these descriptors to study user groups. H3 will use user/movie history available before the rating being predicted. Full-history user summaries must not be used directly for prediction. Current TMDb scores and popularity are excluded from these historical baselines. Tags and tag-genome features are not yet included in the analysis.

## Rating baselines

Ratings were split by time into {splits['train']:,} training, {splits['validation']:,} validation and {splits['test']:,} test events (approximately 70/15/15). Equal timestamps stayed together. Both averages were calculated from training ratings only.

The global baseline predicts {b['training_global_mean']:.2f} for every rating. The movie baseline predicts the movie's training average, or the global average if the movie has no training ratings.

| Baseline | Test RMSE | Test MAE |
|---|---:|---:|
| Global average | {test['global_average']['rmse']:.4f} | {test['global_average']['mae']:.4f} |
| Movie average + fallback | {test['movie_average']['rmse']:.4f} | {test['movie_average']['mae']:.4f} |

MAE is the average absolute error; RMSE gives larger errors more weight. Lower values are better. The movie-average baseline had smaller errors, but no supervised model has been evaluated here, so this does not confirm H3. Clustering is deferred, so this notebook does not test H2.

![Prediction errors on the same held-out test ratings.](baseline_errors.png)

Measured source run: {result['run_id']}; source ETL: {result['source_runs'][0]['run_id']}. Charts and numbers use saved measured results, not a new experiment.
'''
    (out / 'REPORT_SECTION.md').write_text(text, encoding='utf-8')
    root_text = text.replace('(eda_overview.png)', f"({result['run_id']}/eda_overview.png)").replace('(baseline_errors.png)', f"({result['run_id']}/baseline_errors.png)")
    (root / 'REPORT_SECTION.md').write_text(root_text, encoding='utf-8')
    save_json(root / 'source.json', {'source_run_id':result['run_id'], 'source_results_directory':str(source),
              'report_directory':str(out), 'scope':'EDA, prepared descriptors and rating baselines; no clustering conclusions'})
    return root / 'REPORT_SECTION.md'


if __name__ == '__main__':
    build_report(json.loads(Path('reports/results/mining_preliminary/latest.json').read_text()))
