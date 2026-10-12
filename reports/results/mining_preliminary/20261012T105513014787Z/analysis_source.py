"""Read-only, full-data progress-report mining, executed through a notebook."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import platform
import time

import duckdb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import (adjusted_rand_score, calinski_harabasz_score,
                             davies_bouldin_score, silhouette_score)
from sklearn.preprocessing import StandardScaler

SEED = 42
K_VALUES = [2, 3, 4, 5]
SILHOUETTE_USERS = 2000
COLORS = ['#244b68', '#c47c32', '#5e8c73', '#945e74', '#7e78a3']
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                     'axes.spines.right': False, 'figure.dpi': 120})


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def figure(ctx, name, fig):
    fig.tight_layout()
    fig.savefig(ctx.out / name, dpi=180, bbox_inches='tight')
    plt.close(fig)


class Session:
    def __init__(self, warehouse='warehouse/movielens.duckdb'):
        self.started = time.perf_counter()
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.root = Path('reports/results/mining_preliminary')
        self.out = self.root / self.run_id
        self.data = Path('data/processed/mining_preliminary') / self.run_id
        self.out.mkdir(parents=True, exist_ok=False)
        self.data.mkdir(parents=True, exist_ok=False)
        self.con = duckdb.connect(warehouse, read_only=True)
        self.con.execute("SET threads=1; SET memory_limit='2GB'; SET preserve_insertion_order=false; SET TimeZone='UTC'")
        self.before = self.signature()
        self.source_runs = self.con.execute('SELECT * FROM ETLRun ORDER BY finished_at DESC LIMIT 3').fetchdf().to_dict('records')
        packages = ['duckdb', 'numpy', 'pandas', 'scikit-learn', 'scipy', 'matplotlib', 'nbformat', 'nbclient', 'ipykernel']
        self.metadata = {
            'run_id': self.run_id, 'started_at': timestamp(), 'warehouse': warehouse,
            'source_runs': self.source_runs, 'warehouse_signature': self.before,
            'data_scope': 'all published MovieLens rating events; no event sample',
            'python': platform.python_version(), 'platform': platform.platform(),
            'packages': {p: importlib.metadata.version(p) for p in packages},
            'seed': SEED, 'sql_threads': 1, 'sql_memory_limit': '2GB',
            'source_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        self.phase('open read-only warehouse')

    def phase(self, name):
        save_json(self.root / 'progress.json', {'run_id': self.run_id, 'phase': name,
                  'updated_at': timestamp(), 'elapsed_seconds': time.perf_counter() - self.started})
        print(name, flush=True)

    def signature(self):
        row = self.con.execute('''SELECT count(*) ratings,count(DISTINCT user_key) rating_users,
            count(DISTINCT movie_key) rated_movies,sum(rating) rating_sum,
            min(rating_timestamp) first_rating,max(rating_timestamp) last_rating FROM FactRatings''').fetchone()
        keys = ['ratings', 'rating_users', 'rated_movies', 'rating_sum', 'first_rating', 'last_rating']
        return {k: str(v) if isinstance(v, datetime) else v for k, v in zip(keys, row)}


def run_eda(ctx):
    ctx.phase('EDA: aggregate every rating into user and movie summaries')
    begin = time.perf_counter()
    c = ctx.con
    c.execute('''CREATE TEMP TABLE prelim_users AS
        SELECT user_key,count(*) rating_count,avg(rating) mean_rating,
        stddev_pop(rating) rating_std,avg(CASE WHEN rating>=4 THEN 1.0 ELSE 0 END) high_rating_share,
        date_diff('day',min(rating_timestamp),max(rating_timestamp)) activity_span_days
        FROM FactRatings GROUP BY user_key''')
    c.execute('''CREATE TEMP TABLE prelim_movies AS SELECT movie_key,count(*) rating_count,
        sum(rating) rating_sum,avg(rating) mean_rating FROM FactRatings GROUP BY movie_key''')
    rating = c.execute('SELECT rating,count(*) rating_count FROM FactRatings GROUP BY rating ORDER BY rating').fetchdf()
    monthly = c.execute("SELECT date_trunc('month',rating_timestamp) AS rating_month,count(*) rating_count,avg(rating) mean_rating FROM FactRatings GROUP BY rating_month ORDER BY rating_month").fetchdf()
    users = c.execute('SELECT * FROM prelim_users ORDER BY user_key').fetchdf()
    movies = c.execute('SELECT * FROM prelim_movies ORDER BY movie_key').fetchdf()
    genre = c.execute('''SELECT g.genre_name,sum(m.rating_count*b.allocation_weight) allocated_ratings,
        sum(m.rating_sum*b.allocation_weight)/sum(m.rating_count*b.allocation_weight) mean_rating
        FROM prelim_movies m JOIN BridgeMovieGenre b USING(movie_key)
        JOIN DimGenre g USING(genre_key) GROUP BY g.genre_name ORDER BY allocated_ratings DESC''').fetchdf()
    if int(rating.rating_count.sum()) != ctx.before['ratings']:
        raise ValueError('EDA rating counts did not reconcile')
    if not np.isclose(genre.allocated_ratings.sum(), ctx.before['ratings'], rtol=1e-10):
        raise ValueError('Genre allocations did not reconcile to all ratings')
    for name, frame in [('rating_distribution', rating), ('monthly_activity', monthly),
                        ('genre_activity', genre)]:
        frame.to_csv(ctx.out / (name + '.csv'), index=False)
    summary = {
        'ratings': ctx.before['ratings'], 'rating_users': len(users), 'rated_movies': len(movies),
        'catalog_movies': c.execute('SELECT count(*) FROM DimMovie').fetchone()[0],
        'first_rating': ctx.before['first_rating'], 'last_rating': ctx.before['last_rating'],
        'mean_rating': float(ctx.before['rating_sum'] / ctx.before['ratings']),
        'most_common_rating': float(rating.loc[rating.rating_count.idxmax(), 'rating']),
        'user_activity_quantiles': {str(q): float(users.rating_count.quantile(q)) for q in [.25, .5, .9, .99]},
        'movie_activity_quantiles': {str(q): float(movies.rating_count.quantile(q)) for q in [.25, .5, .9, .99]},
        'seconds': time.perf_counter() - begin,
        'genre_grain': 'fractional allocation of each rating across its MovieLens genres; total equals ratings',
    }
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.bar(rating.rating.astype(str), rating.rating_count / 1e6, color=COLORS[0])
    ax.set(xlabel='MovieLens rating', ylabel='Rating events (millions)', title='Rating distribution — all 20M events')
    figure(ctx, 'eda_rating_distribution.png', fig)
    fig, axes = plt.subplots(2, 1, figsize=(8, 6))
    axes[0].plot(monthly.rating_month, monthly.rating_count / 1e6, color=COLORS[0])
    axes[0].set(xlabel='Rating month (UTC)', ylabel='Events (millions)', title='Historical rating activity')
    for frame, label, color in [(users, 'Users', COLORS[0]), (movies, 'Movies', COLORS[1])]:
        count = frame.rating_count.to_numpy()
        bins = np.geomspace(max(1, count.min()), count.max() + 1, 35)
        axes[1].hist(count, bins=bins, alpha=.65, label=label, color=color)
    axes[1].set(xscale='log', yscale='log', xlabel='Ratings per user or movie', ylabel='Number of users / movies', title='Activity is concentrated in a long tail')
    axes[1].legend()
    figure(ctx, 'eda_activity.png', fig)
    fig, ax = plt.subplots(figsize=(8, 6))
    ordered = genre.sort_values('allocated_ratings')
    ax.barh(ordered.genre_name, ordered.allocated_ratings / 1e6, color=COLORS[0])
    ax.set(xlabel='Allocated rating events (millions)', title='MovieLens genre exposure — weighted genre bridge')
    figure(ctx, 'eda_genres.png', fig)
    save_json(ctx.out / 'eda.json', summary)
    return summary


def prepare_features(ctx):
    ctx.phase('H2: build weighted genre shares for every rating-active user')
    begin = time.perf_counter()
    users = ctx.con.execute('SELECT * FROM prelim_users ORDER BY user_key').fetchdf()
    genre = ctx.con.execute('''SELECT r.user_key,g.genre_name,sum(b.allocation_weight) allocated_ratings
        FROM FactRatings r JOIN BridgeMovieGenre b USING(movie_key)
        JOIN DimGenre g USING(genre_key) GROUP BY r.user_key,g.genre_name''').fetchdf()
    wide = genre.pivot(index='user_key', columns='genre_name', values='allocated_ratings').fillna(0)
    wide = wide.reindex(users.user_key).div(users.set_index('user_key').rating_count, axis=0).add_prefix('genre_')
    users = users.join(wide, on='user_key')
    if not np.allclose(users[wide.columns].sum(axis=1), 1, atol=1e-8):
        raise ValueError('User genre shares do not sum to one')
    users['log_rating_count'] = np.log1p(users.rating_count)
    users['log_activity_span_days'] = np.log1p(users.activity_span_days)
    features = ['log_rating_count', 'mean_rating', 'rating_std', 'high_rating_share', 'log_activity_span_days'] + list(wide.columns)
    if not np.isfinite(users[features].to_numpy()).all():
        raise ValueError('User features contain missing or non-finite values')
    users.to_parquet(ctx.data / 'user_features.parquet', index=False)
    ctx.features = features
    ctx.feature_seconds = time.perf_counter() - begin
    save_json(ctx.out / 'feature_definitions.json', {
        'analysis_unit': 'one rating-active user', 'users': len(users),
        'all_ratings_used': ctx.before['ratings'], 'features': features,
        'definitions': {
            'log_rating_count': 'log(1 + total user rating events)',
            'mean_rating': 'average historical rating',
            'rating_std': 'population standard deviation of historical ratings',
            'high_rating_share': 'fraction of ratings >= 4.0',
            'log_activity_span_days': 'log(1 + days between first and last rating)',
            'genre_*': 'sum of fractional genre allocations / user rating count',
        },
        'preprocessing': 'StandardScaler on descriptive user features; zero genre exposure means no observed rated movies of that genre',
        'missing_feature_values': 0, 'numeric_imputation': 'none required',
        'excluded': ['user/movie IDs as numeric predictors', 'TMDb popularity/votes', 'tags/genome not present in current rating warehouse'],
        'timing_scope': 'full history is valid for descriptive clustering; these summaries are not H3 predictive features',
    })
    return users


def run_clustering(ctx, users):
    ctx.phase('H2: fit and evaluate full-user clustering candidates')
    started = time.perf_counter()
    scaler = StandardScaler()
    x = scaler.fit_transform(users[ctx.features])
    sample = np.sort(np.random.default_rng(SEED).choice(len(users), min(SILHOUETTE_USERS, len(users)), replace=False))
    candidates, fitted = [], {}
    for k in K_VALUES:
        ctx.phase(f'H2: k={k}, all {len(users):,} users')
        begin = time.perf_counter()
        model = MiniBatchKMeans(n_clusters=k, batch_size=4096, n_init=10, max_iter=100, random_state=SEED)
        labels = model.fit_predict(x)
        fit_seconds = time.perf_counter() - begin
        alternate = MiniBatchKMeans(n_clusters=k, batch_size=4096, n_init=10, max_iter=100, random_state=SEED + 1).fit_predict(x)
        if len(np.unique(labels)) != k or len(np.unique(labels[sample])) < 2:
            raise ValueError('Degenerate preliminary clustering result')
        result = {'k': k, 'inertia': float(model.inertia_), 'fit_seconds': fit_seconds,
            'silhouette': float(silhouette_score(x[sample], labels[sample])),
            'silhouette_metric_users': len(sample),
            'davies_bouldin_full_users': float(davies_bouldin_score(x, labels)),
            'calinski_harabasz_full_users': float(calinski_harabasz_score(x, labels)),
            'seed_stability_ari_full_users': float(adjusted_rand_score(labels, alternate)),
            'sizes': {str(i): int(np.sum(labels == i)) for i in range(k)}}
        candidates.append(result)
        fitted[k] = (model, labels)
    selected = max(candidates, key=lambda r: r['silhouette'])
    model, labels = fitted[selected['k']]
    frame = users.copy()
    frame['cluster'] = labels
    frame[['user_key', 'cluster']].to_parquet(ctx.data / 'user_clusters.parquet', index=False)
    profiles = frame.drop(columns='user_key').groupby('cluster').mean()
    profiles.insert(0, 'users', frame.groupby('cluster').size())
    profiles.to_csv(ctx.out / 'cluster_profiles.csv', index_label='cluster')
    pd.DataFrame(candidates).drop(columns=['sizes']).to_csv(ctx.out / 'cluster_candidates.csv', index=False)
    pd.DataFrame(model.cluster_centers_, columns=ctx.features).to_csv(ctx.out / 'standardized_cluster_centers.csv', index_label='cluster')
    import pickle
    with (ctx.data / 'clustering_model.pkl').open('wb') as f:
        pickle.dump({'scaler': scaler, 'model': model, 'features': ctx.features}, f)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    axes[0].bar([str(i) for i in profiles.index], profiles.users, color=COLORS[:len(profiles)])
    axes[0].set(xlabel='Cluster ID', ylabel='Users', title='Every user has a cluster assignment')
    axes[1].plot([r['k'] for r in candidates], [r['silhouette'] for r in candidates], marker='o', color=COLORS[0])
    axes[1].set(xlabel='Candidate cluster count k', ylabel='Sampled silhouette', title='Preliminary comparison (fixed 2,000 users)', xticks=K_VALUES)
    figure(ctx, 'h2_cluster_sizes_quality.png', fig)
    genre_columns = [f for f in ctx.features if f.startswith('genre_')]
    fig, ax = plt.subplots(figsize=(10, 3 + .35 * len(profiles)))
    image = ax.imshow(profiles[genre_columns].to_numpy(), cmap='Blues', aspect='auto', vmin=0)
    ax.set(yticks=range(len(profiles)), yticklabels=[f'Cluster {i}' for i in profiles.index],
           xticks=range(len(genre_columns)), xticklabels=[f[6:] for f in genre_columns], title='Observed genre shares by cluster')
    plt.setp(ax.get_xticklabels(), rotation=55, ha='right')
    fig.colorbar(image, ax=ax, label='Mean allocated genre share')
    figure(ctx, 'h2_genre_profiles.png', fig)
    result = {'users': len(users), 'features': ctx.features, 'feature_count': len(ctx.features),
        'feature_seconds': ctx.feature_seconds, 'seed': SEED, 'alternate_seed': SEED + 1,
        'algorithm': 'MiniBatchKMeans', 'parameters': {'batch_size': 4096, 'n_init': 10, 'max_iter': 100},
        'candidates': candidates, 'selected_k': selected['k'],
        'selection': 'highest silhouette among k=2,3,4,5; exploratory, not final model selection',
        'metric_sampling': 'Silhouette only uses a fixed seeded 2,000-user subset because pairwise distance cost is quadratic. All users are fitted/assigned; DB, CH and ARI use all users.',
        'profiles': profiles.reset_index().to_dict('records'), 'seconds': time.perf_counter() - started}
    save_json(ctx.out / 'clustering.json', result)
    return result


def run_baselines(ctx):
    ctx.phase('H3: determine chronological boundaries using every rating event')
    started = time.perf_counter()
    c = ctx.con
    train_end, test_start = c.execute('SELECT quantile_disc(rating_timestamp,[0.70,0.85]) FROM FactRatings').fetchone()[0]
    if train_end >= test_start:
        raise ValueError('Chronological boundaries are not distinct')
    c.execute('CREATE TEMP TABLE training_movies AS SELECT movie_key,count(*) n,avg(rating) mean_rating FROM FactRatings WHERE rating_timestamp < ? GROUP BY movie_key', [train_end])
    c.execute('CREATE TEMP TABLE training_users AS SELECT DISTINCT user_key FROM FactRatings WHERE rating_timestamp < ?', [train_end])
    mean, n_train = c.execute('SELECT sum(mean_rating*n)/sum(n),sum(n) FROM training_movies').fetchone()
    partition_sql = '''SELECT CASE WHEN rating_timestamp < ? THEN 'train'
        WHEN rating_timestamp < ? THEN 'validation' ELSE 'test' END split,
        count(*) ratings,count(DISTINCT user_key) users,count(DISTINCT movie_key) movies,
        min(rating_timestamp) first_rating,max(rating_timestamp) last_rating
        FROM FactRatings GROUP BY split'''
    splits = c.execute(partition_sql, [train_end, test_start]).fetchdf()
    if int(splits.ratings.sum()) != ctx.before['ratings'] or len(splits) != 3:
        raise ValueError('Full chronological partitions do not reconcile')
    bounds = splits.set_index('split')
    if not (bounds.loc['train','last_rating'] < bounds.loc['validation','first_rating']
            and bounds.loc['validation','last_rating'] < bounds.loc['test','first_rating']):
        raise ValueError('Chronological partitions overlap or split ties')
    ctx.phase('H3: evaluate global/movie averages using training statistics only')
    scored = '''WITH scored AS (
        SELECT CASE WHEN f.rating_timestamp < ? THEN 'validation' ELSE 'test' END split,
        f.rating,coalesce(m.mean_rating,?) movie_prediction,
        m.movie_key IS NULL unseen_movie,u.user_key IS NULL unseen_user
        FROM FactRatings f LEFT JOIN training_movies m USING(movie_key)
        LEFT JOIN training_users u USING(user_key) WHERE f.rating_timestamp >= ?)
        SELECT split,'global_average' model,count(*) ratings,
        sqrt(avg(power(rating-?,2))) rmse,avg(abs(rating-?)) mae,
        count(*) FILTER(WHERE unseen_movie) global_fallback_events,
        count(*) FILTER(WHERE unseen_user) unseen_user_events
        FROM scored GROUP BY split
        UNION ALL SELECT split,'movie_average' model,count(*) ratings,
        sqrt(avg(power(rating-movie_prediction,2))) rmse,avg(abs(rating-movie_prediction)) mae,
        count(*) FILTER(WHERE unseen_movie) global_fallback_events,
        count(*) FILTER(WHERE unseen_user) unseen_user_events FROM scored GROUP BY split'''
    table = c.execute(scored, [test_start, mean, train_end, mean, mean]).fetchdf().sort_values(['split','model'])
    cohort = c.execute('''SELECT CASE WHEN m.movie_key IS NULL THEN 'unseen_movie' ELSE 'seen_movie' END cohort,
        count(*) ratings,sqrt(avg(power(f.rating-coalesce(m.mean_rating,?),2))) movie_baseline_rmse,
        avg(abs(f.rating-coalesce(m.mean_rating,?))) movie_baseline_mae
        FROM FactRatings f LEFT JOIN training_movies m USING(movie_key)
        WHERE f.rating_timestamp >= ? GROUP BY cohort''', [mean, mean, test_start]).fetchdf()
    splits.to_csv(ctx.out / 'chronological_splits.csv', index=False)
    table.to_csv(ctx.out / 'baseline_metrics.csv', index=False)
    cohort.to_csv(ctx.out / 'test_movie_cohorts.csv', index=False)
    test = table[table.split == 'test'].set_index('model')
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.6))
    for ax, metric in zip(axes, ['rmse', 'mae']):
        values = test.loc[['global_average','movie_average'], metric]
        ax.bar(['Global average','Movie average'], values, color=COLORS[:2])
        ax.set(ylabel=metric.upper(), title=f'Chronological test {metric.upper()} (lower is better)', ylim=(0, max(values)*1.2))
        for i, v in enumerate(values):
            ax.text(i, v + .02, f'{v:.4f}', ha='center')
    figure(ctx, 'h3_baseline_errors.png', fig)
    result = {'target': 'observed MovieLens rating on 0.5–5.0 scale',
        'scope': 'all rating events partitioned by UTC timestamp; no pre-split event sample',
        'requested_fractions': [.70,.15,.15], 'train_end_exclusive_utc': str(train_end),
        'test_start_inclusive_utc': str(test_start),
        'tie_policy': 'all equal timestamps stay in one partition; actual fractions may differ slightly',
        'splits': splits.to_dict('records'), 'training_global_mean': float(mean),
        'training_ratings': int(n_train), 'metrics': table.to_dict('records'),
        'test_movie_cohorts': cohort.to_dict('records'),
        'features': 'only training-period global or per-movie mean; identifiers are group keys, not numeric predictors',
        'cold_movie_policy': 'unseen movies fall back to the training global mean',
        'excluded': 'TMDb current popularity/votes, tags/genome, and H2 full-history summaries',
        'seconds': time.perf_counter()-started,
        'limitation': 'Train-only baselines do not demonstrate H3 feature-model improvement; predictive features/model fitting remain future work.'}
    save_json(ctx.out / 'baselines.json', result)
    return result


def report_section(ctx, eda, clusters, baselines, prefix=''):
    best = next(r for r in clusters['candidates'] if r['k'] == clusters['selected_k'])
    rows = ['# Preliminary mining pipeline and exploratory data analysis', '',
        f"Analysis used the current published MovieLens 20M DuckDB warehouse: {eda['ratings']:,} rating events, {eda['rating_users']:,} rating-active users and {eda['rated_movies']:,} rated movies ({eda['catalog_movies']:,} catalog entries). No rating events or fitting users were sampled. The warehouse was read-only; summaries used for this run reconciled before and after analysis. Source ETL run: `{ctx.source_runs[0]['run_id']}`.", '',
        '## Preparation and EDA', '',
        f"Ratings span {eda['first_rating']} to {eda['last_rating']} UTC. The mean is {eda['mean_rating']:.4f}, and the most frequent score is {eda['most_common_rating']:.1f}. Median activity is {eda['user_activity_quantiles']['0.5']:.0f} ratings per user and {eda['movie_activity_quantiles']['0.5']:.0f} per rated movie; the 90th percentiles are {eda['user_activity_quantiles']['0.9']:.0f} and {eda['movie_activity_quantiles']['0.9']:.0f}, respectively. These are recorded ratings, not verified movie views.", '',
        'Rating distributions, monthly activity and long-tail user/movie activity were aggregated from every fact row. Multi-genre movies were handled using the warehouse bridge allocation weight; allocated genre counts reconcile to the total event count. Numeric rating imputation was unnecessary for the validated fact table. Absent observed user/genre exposure was encoded as zero exposure, without asserting dislike.', '',
        f'![Rating distribution]({prefix}eda_rating_distribution.png)',
        f'![Rating and user/movie activity]({prefix}eda_activity.png)',
        f'![Allocated genre exposure]({prefix}eda_genres.png)', '',
        '## H2: preliminary user clustering', '',
        f"One feature row was produced for each of {clusters['users']:,} users. The {clusters['feature_count']} features are log(1 + rating count), mean rating, population rating standard deviation, share of scores at least 4.0, log(1 + activity-span days), and fractional rating shares across MovieLens genres. StandardScaler standardized the descriptors. There were no missing/non-finite feature values. Identifiers, current TMDb popularity/votes, and unavailable tag/genome features were excluded.", '',
        'MiniBatchKMeans was fitted to all users for k=2,3,4,5 (seed 42, batch size 4,096, 10 initializations, maximum 100 iterations). The silhouette score uses the same seeded 2,000-user metric subset for each candidate because exact pairwise evaluation on every user is costly. All users remain fitted and assigned; Davies–Bouldin, Calinski–Harabasz and seed-stability ARI are computed on all users.', '',
        '| k | Silhouette (2,000 users) | Davies–Bouldin ↓ | Calinski–Harabasz ↑ | Seed ARI | Fit seconds |',
        '|---:|---:|---:|---:|---:|---:|']
    for r in clusters['candidates']:
        rows.append(f"| {r['k']} | {r['silhouette']:.4f} | {r['davies_bouldin_full_users']:.4f} | {r['calinski_harabasz_full_users']:.1f} | {r['seed_stability_ari_full_users']:.4f} | {r['fit_seconds']:.2f} |")
    rows += ['', f"The preliminary selection is k={best['k']} using the highest sampled silhouette ({best['silhouette']:.4f}). This comparison is exploratory. A silhouette near zero indicates overlapping groups; seed ARI measures consistency across initializations rather than correctness.", '',
        '| Cluster | Users | Mean ratings/user | Mean score | Mean rating SD | Share ≥4 | Largest allocated genre shares |',
        '|---:|---:|---:|---:|---:|---:|---|']
    for p in clusters['profiles']:
        top = sorted([(k[6:], v) for k,v in p.items() if k.startswith('genre_')], key=lambda t:t[1], reverse=True)[:3]
        rows.append(f"| {int(p['cluster'])} | {int(p['users']):,} | {p['rating_count']:.1f} | {p['mean_rating']:.3f} | {p['rating_std']:.3f} | {p['high_rating_share']:.1%} | "+'; '.join(f'{name} {v:.1%}' for name,v in top)+' |')
    rows += ['', 'Cluster IDs have no inherent order or demographic meaning. Profiles describe behavior in this observed dataset; the preliminary analysis does not establish causal or universal preference groups.', '',
        f'![Cluster sizes and quality]({prefix}h2_cluster_sizes_quality.png)',
        f'![Cluster genre profiles]({prefix}h2_genre_profiles.png)', '',
        '## H3: chronological rating baselines', '',
        f"All rating events were divided by timestamp using the 70th and 85th percentile boundaries. Training uses timestamps strictly before {baselines['train_end_exclusive_utc']} UTC; validation uses that boundary up to {baselines['test_start_inclusive_utc']} UTC; test uses timestamps at or after the latter. Equal timestamps stay together. Splitting preceded computation of all prediction statistics.", '',
        '| Partition | Ratings | First rating UTC | Last rating UTC |',
        '|---|---:|---|---|']
    for split in ['train','validation','test']:
        p = next(r for r in baselines['splits'] if r['split'] == split)
        rows.append(f"| {split} | {int(p['ratings']):,} | {p['first_rating']} | {p['last_rating']} |")
    rows += ['', f"The global baseline predicts the training mean ({baselines['training_global_mean']:.4f}) for every held-out event. The movie baseline predicts a movie's training-period mean and falls back to the training global mean for unseen movies. No held-out rating contributed to training statistics.", '',
        '| Partition | Baseline | Events | RMSE ↓ | MAE ↓ | Unseen-movie fallback events |',
        '|---|---|---:|---:|---:|---:|']
    for p in sorted(baselines['metrics'], key=lambda r:(r['split']!='validation', r['model'])):
        fallback = f"{int(p['global_fallback_events']):,}" if p['model']=='movie_average' else 'all events use global mean'
        rows.append(f"| {p['split']} | {p['model']} | {int(p['ratings']):,} | {p['rmse']:.4f} | {p['mae']:.4f} | {fallback} |")
    test = {r['model']:r for r in baselines['metrics'] if r['split']=='test'}
    direction = 'lower' if test['movie_average']['rmse'] < test['global_average']['rmse'] else 'higher'
    rows += ['', f"The movie-average baseline has {direction} test RMSE than the global baseline on this split. These results establish reference performance; H3 has not yet been confirmed because a supervised feature model has not been evaluated against them.", '',
        f'![Chronological baseline errors]({prefix}h3_baseline_errors.png)', '',
        '## Feature strategy and limitations', '',
        'The next H3 model should use user-history means/counts and movie-history statistics computed from information available before each prediction, plus MovieLens genre descriptors. Training-row features must exclude their own targets and later labels. Full-history H2 summaries must not be reused as predictive features. Current TMDb ratings, vote counts and popularity are not temporally aligned to the 1995–2015 MovieLens targets and were excluded. Tags and genome scores are not loaded into this project\'s active rating warehouse, so their contribution remains future work.', '',
        f"Reproducibility: Python {ctx.metadata['python']}, DuckDB {ctx.metadata['packages']['duckdb']}, scikit-learn {ctx.metadata['packages']['scikit-learn']}, platform `{ctx.metadata['platform']}`, seed 42, one DuckDB thread and a 2 GB SQL memory budget. Run ID `{ctx.run_id}`. The notebook, CSV tables, features/model files, package versions and source-code fingerprint accompany this section. Metrics are descriptive/preliminary; no final predictive-model or production recommendation claim is made.", '',
        '## Method references', '',
        '- GroupLens: https://grouplens.org/datasets/movielens/20m/',
        '- MiniBatchKMeans: https://scikit-learn.org/1.6/modules/generated/sklearn.cluster.MiniBatchKMeans.html',
        '- Silhouette score: https://scikit-learn.org/1.6/modules/generated/sklearn.metrics.silhouette_score.html',
        '- StandardScaler: https://scikit-learn.org/1.6/modules/generated/sklearn.preprocessing.StandardScaler.html', '']
    return '\n'.join(rows)


def finalize(ctx, eda, clusters, baselines):
    ctx.phase('save measured results and report section')
    after = ctx.signature()
    if after != ctx.before:
        raise ValueError('Read-only warehouse signature changed during analysis')
    ctx.con.close()
    result = {**ctx.metadata, 'finished_at': timestamp(), 'status': 'success',
        'warehouse_signature_unchanged': True, 'eda': eda, 'clustering': clusters,
        'baselines': baselines, 'elapsed_seconds': time.perf_counter()-ctx.started,
        'results_directory': str(ctx.out), 'derived_data_directory': str(ctx.data)}
    save_json(ctx.out / 'run.json', result)
    save_json(ctx.root / 'latest.json', result)
    (ctx.out / 'REPORT_SECTION.md').write_text(report_section(ctx, eda, clusters, baselines), encoding='utf-8')
    (ctx.root / 'REPORT_SECTION.md').write_text(report_section(ctx, eda, clusters, baselines, ctx.run_id+'/'), encoding='utf-8')
    ctx.phase('complete')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--notebook', default='notebooks/05_mining_preliminary.ipynb')
    args = parser.parse_args()
    import nbformat
    from nbclient import NotebookClient
    path = Path(args.notebook)
    nb = nbformat.read(path, as_version=4)
    for cell in nb.cells:
        if cell.cell_type == 'code':
            cell.outputs = []
            cell.execution_count = None
    print('Executing full-data preliminary mining notebook against read-only DuckDB.', flush=True)
    def started(cell, cell_index, **kwargs):
        print(f"Notebook cell {cell_index+1}: {cell.metadata.get('stage','analysis')}", flush=True)
    client = NotebookClient(nb, timeout=1800, kernel_name='python3', resources={'metadata': {'path': '/app'}}, on_cell_start=started)
    try:
        client.execute()
    finally:
        nbformat.write(nb, path)
    result = json.loads(Path('reports/results/mining_preliminary/latest.json').read_text())
    print(json.dumps({'status': result['status'], 'run_id': result['run_id'],
          'ratings': result['eda']['ratings'], 'users_clustered': result['clustering']['users'],
          'selected_k': result['clustering']['selected_k'],
          'test_baselines': [r for r in result['baselines']['metrics'] if r['split']=='test'],
          'elapsed_seconds': result['elapsed_seconds']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
