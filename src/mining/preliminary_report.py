"""Compact report section and composite figures from measured output only."""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mining.preliminary import COLORS, figure


def build_report():
    root = Path('reports/results/mining_preliminary')
    r = json.loads((root/'latest.json').read_text())
    out = Path(r['results_directory'])
    class Context:
        pass
    ctx = Context()
    ctx.out = out
    ratings = pd.read_csv(out/'rating_distribution.csv')
    monthly = pd.read_csv(out/'monthly_activity.csv', parse_dates=['rating_month'])
    genres = pd.read_csv(out/'genre_activity.csv')
    profiles = pd.read_csv(out/'cluster_profiles.csv')
    features = pd.read_parquet(Path(r['derived_data_directory'])/'user_features.parquet')
    fig, axes = plt.subplots(2,2,figsize=(10,6))
    axes[0,0].bar(ratings.rating.astype(str), ratings.rating_count/1e6, color=COLORS[0])
    axes[0,0].set(xlabel='Rating', ylabel='Events (millions)', title='(a) Rating distribution')
    axes[0,1].plot(monthly.rating_month, monthly.rating_count/1e6, color=COLORS[0])
    axes[0,1].set(xlabel='Rating month (UTC)', ylabel='Events (millions)', title='(b) Historical activity')
    axes[1,0].hist(features.rating_count, bins=np.geomspace(features.rating_count.min(),features.rating_count.max()+1,35), color=COLORS[0])
    axes[1,0].set(xscale='log',xlabel='Ratings per user (log scale)',ylabel='Users',title='(c) User activity')
    top = genres.head(10).iloc[::-1]
    axes[1,1].barh(top.genre_name, top.allocated_ratings/1e6, color=COLORS[0])
    axes[1,1].set(xlabel='Allocated events (millions)',title='(d) Ten largest genre exposures')
    figure(ctx,'eda_overview.png',fig)
    cluster = r['clustering']
    baselines = r['baselines']
    best = next(v for v in cluster['candidates'] if v['k']==cluster['selected_k'])
    test = {v['model']:v for v in baselines['metrics'] if v['split']=='test'}
    fig,axes = plt.subplots(1,2,figsize=(10,3.8))
    genre_names = genres.head(10).genre_name.tolist()
    values = profiles[['genre_'+g for g in genre_names]].to_numpy()
    im = axes[0].imshow(values,cmap='Blues',aspect='auto',vmin=0)
    axes[0].set(xticks=range(10),xticklabels=genre_names,yticks=range(len(profiles)),
        yticklabels=['Cluster '+str(int(v)) for v in profiles.cluster],title='(a) Cluster genre profiles')
    plt.setp(axes[0].get_xticklabels(),rotation=55,ha='right')
    fig.colorbar(im,ax=axes[0],label='Mean allocated share',shrink=.8)
    x = np.arange(2)
    for i,(name,label) in enumerate([('global_average','Global mean'),('movie_average','Movie mean')]):
        v = [test[name]['rmse'],test[name]['mae']]
        bars = axes[1].bar(x+(i-.5)*.35,v,width=.35,color=COLORS[i],label=label)
        for bar,number in zip(bars,v):
            axes[1].text(bar.get_x()+bar.get_width()/2,number+.02,f'{number:.4f}',ha='center',fontsize=8)
    axes[1].set(xticks=x,xticklabels=['RMSE','MAE'],ylabel='Rating error',title='(b) Chronological test baselines',ylim=(0,1.25))
    axes[1].legend(loc='upper right')
    figure(ctx,'mining_results_overview.png',fig)
    e = r['eda']
    splits = {v['split']:v for v in baselines['splits']}
    fallback = test['movie_average']['global_fallback_events']
    unseen_user = test['movie_average']['unseen_user_events']
    text = [
        '# Preliminary mining and exploratory data analysis', '',
        '## Data preparation and EDA', '',
        f"The analysis read the current DuckDB warehouse containing **{e['ratings']:,} MovieLens rating events**, **{e['rating_users']:,} rating-active users** and **{e['rated_movies']:,} rated movies** ({e['catalog_movies']:,} metadata records). All events were used; clustering received the complete user feature table. The warehouse was mounted/read-only and its count/sum summary remained unchanged. Tags/genome are not part of this active warehouse; current TMDb rating and popularity measures were excluded from historic prediction.", '',
        f"Ratings cover 1995–2015 UTC. The mean score was **{e['mean_rating']:.4f}** and the most common score was **{e['most_common_rating']:.1f}**. Median activity was **{e['user_activity_quantiles']['0.5']:.0f} ratings per user** and **{e['movie_activity_quantiles']['0.5']:.0f} per rated movie**. Numeric rating imputation was unnecessary for the validated facts. Multi-genre events were fractionally allocated through the movie/genre bridge; allocated counts reconcile to the total. Figure 1 shows rating scores, time, user activity and genre exposure. These events represent recorded ratings, not verified views.", '',
        f"![Figure 1. EDA using all ratings.]({r['run_id']}/eda_overview.png)", '',
        '## H2: user features and preliminary clustering', '',
        f"Each user has **{cluster['feature_count']} features**: log(1+rating count), mean rating, population rating standard deviation, share of scores >=4, log(1+activity span in days), and weighted shares across 20 MovieLens genre categories. StandardScaler standardized the descriptors; all feature values were finite. Zero genre exposure records absence of observed ratings, rather than dislike. MiniBatchKMeans receives all users and optimizes internally with minibatches (batch=4,096; n_init=10; max_iter=100; seed=42).", '',
        '| k | Silhouette | Full-user DB ↓ | Seed ARI |', '|---:|---:|---:|---:|']
    for v in cluster['candidates']:
        text.append(f"| {v['k']} | {v['silhouette']:.4f} | {v['davies_bouldin_full_users']:.4f} | {v['seed_stability_ari_full_users']:.4f} |")
    text += ['', f"The highest candidate silhouette selected **k={best['k']}**, with silhouette **{best['silhouette']:.4f}**, Davies–Bouldin **{best['davies_bouldin_full_users']:.4f}** and Calinski–Harabasz **{best['calinski_harabasz_full_users']:.1f}**. Silhouette uses the same seeded 2,000-user metric subset; fitting/assignments and the other metrics use all users. Low silhouette and seed-42/43 ARI **{best['seed_stability_ari_full_users']:.4f}** indicate overlapping, initialization-sensitive groups. The preliminary result does not establish strong preference archetypes or tag-based groups.", '',
        '| Cluster | Users | Mean ratings/user | Mean score | Mean rating SD |', '|---:|---:|---:|---:|---:|']
    for p in cluster['profiles']:
        text.append(f"| {int(p['cluster'])} | {int(p['users']):,} | {p['rating_count']:.1f} | {p['mean_rating']:.3f} | {p['rating_std']:.3f} |")
    text += ['', '## H3: chronological rating baselines', '',
        f"All events were partitioned chronologically into **{splits['train']['ratings']:,} training**, **{splits['validation']['ratings']:,} validation** and **{splits['test']['ratings']:,} test** ratings (approximately 70/15/15). Training ends before **{baselines['train_end_exclusive_utc']} UTC**; test starts at **{baselines['test_start_inclusive_utc']} UTC**. Timestamp ties remain together. Prediction statistics were calculated only after splitting, using training events exclusively.", '',
        f"The global baseline predicts the training mean (**{baselines['training_global_mean']:.4f}**); the movie baseline predicts the training movie mean with global fallback for unseen movies. Neither validation nor test targets enter these means. Both baselines were evaluated on all **{splits['test']['ratings']:,} test events**.", '',
        '| Baseline | Test RMSE ↓ | Test MAE ↓ |', '|---|---:|---:|',
        f"| Global average | {test['global_average']['rmse']:.4f} | {test['global_average']['mae']:.4f} |",
        f"| Movie average + global fallback | {test['movie_average']['rmse']:.4f} | {test['movie_average']['mae']:.4f} |", '',
        f"The movie-average baseline reduced both errors (Figure 2). **{fallback:,} test events ({fallback/splits['test']['ratings']:.1%})** concern movies absent from training and use fallback. **{unseen_user:,} ({unseen_user/splits['test']['ratings']:.1%})** involve users absent from training, which will limit future user-history predictors. Independent NumPy error accumulation over every test event reproduced the SQL RMSE/MAE.", '',
        f"![Figure 2. Preliminary genre profiles and prediction baselines.]({r['run_id']}/mining_results_overview.png)", '',
        '## Feature strategy and remaining work', '',
        'A future supervised model will compare against these baselines using prior-event user/movie counts and rating summaries plus MovieLens genres. Training features must exclude the target and future labels. Full-history H2 descriptors must not be reused as H3 predictors. Current TMDb scores/popularity are not time-aligned to historical targets. H3 improvement remains untested; this milestone provides EDA, preparation, features and reference performance.', '',
        f"Reproducibility: source ETL `{r['source_runs'][0]['run_id']}`; notebook `notebooks/05_mining_preliminary.ipynb`; result run `{r['run_id']}`; Python {r['python']}, DuckDB {r['packages']['duckdb']}, scikit-learn {r['packages']['scikit-learn']}; one SQL thread, 2 GB SQL budget, seed 42. All candidate metrics, validation/test results, CSV profiles, features, model and version/code evidence are saved with the run.", '',
        'References: [MovieLens 20M](https://grouplens.org/datasets/movielens/20m/), [MiniBatchKMeans](https://scikit-learn.org/1.6/modules/generated/sklearn.cluster.MiniBatchKMeans.html), [silhouette](https://scikit-learn.org/1.6/modules/generated/sklearn.metrics.silhouette_score.html).', '']
    short = '\n'.join(text)
    (root/'REPORT_SECTION_SHORT.md').write_text(short,encoding='utf-8')
    (out/'REPORT_SECTION_SHORT.md').write_text(short.replace(r['run_id']+'/', ''),encoding='utf-8')
    source = Path('src/mining/preliminary.py').read_bytes()
    if hashlib.sha256(source).hexdigest() != r['source_code_sha256']:
        raise ValueError('Analysis source changed since the numerical run; preserve that source before formatting')
    (out/'analysis_source.py').write_bytes(source)
    print('Compact report:',root/'REPORT_SECTION_SHORT.md',flush=True)
    return root/'REPORT_SECTION_SHORT.md'


if __name__ == '__main__':
    build_report()
