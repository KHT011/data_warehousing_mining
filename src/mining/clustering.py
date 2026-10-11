import pickle
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans,KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score,adjusted_rand_score
from utils.common import atomic_json,utcnow
from etl.load import connect


def run(cfg):
    with connect(cfg,read_only=True) as con:
        frame=con.execute('''SELECT user_key,count(*) rating_count,avg(rating) mean_rating,stddev_pop(rating) rating_std,
         date_diff('day',min(rating_timestamp),max(rating_timestamp)) activity_span_days FROM FactRatings GROUP BY user_key ORDER BY user_key''').fetchdf()
        genre=con.execute('''SELECT user_key,genre_name,sum(allocation_weight)/max(rating_count) proportion
         FROM FactRatings JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key)
         JOIN (SELECT user_key,count(*) rating_count FROM FactRatings GROUP BY user_key) counts USING(user_key)
         GROUP BY user_key,genre_name''').fetchdf()
    wide=genre.pivot(index='user_key',columns='genre_name',values='proportion').fillna(0).add_prefix('genre_')
    frame=frame.join(wide,on='user_key').fillna(0)
    if not np.allclose(frame[wide.columns].sum(axis=1),1): raise ValueError('Genre proportions do not reconcile')
    frame['log_rating_count']=np.log1p(frame.rating_count)
    features=['log_rating_count','mean_rating','rating_std','activity_span_days']+list(wide.columns)
    imputer=SimpleImputer(strategy='median');scaler=StandardScaler();x=scaler.fit_transform(imputer.fit_transform(frame[features]))
    seed=cfg['project']['seed'];rng=np.random.default_rng(seed);sample=np.sort(rng.choice(len(x),min(cfg['mining']['silhouette_sample_limit'],len(x)),replace=False));scores=[];models={}
    for k in cfg['mining']['cluster_k_values']:
        if k>=len(x): continue
        t=time.perf_counter();model=MiniBatchKMeans(n_clusters=k,batch_size=4096,n_init=3,random_state=seed);labels=model.fit_predict(x);seconds=time.perf_counter()-t
        alternate=MiniBatchKMeans(n_clusters=k,batch_size=4096,n_init=3,random_state=seed+1).fit_predict(x)
        score=float(silhouette_score(x[sample],labels[sample])) if 1<len(np.unique(labels[sample]))<len(sample) else None
        scores.append({'k':k,'inertia':float(model.inertia_),'seconds':seconds,'silhouette':score,'silhouette_sample':len(sample),'seed_stability_ari':float(adjusted_rand_score(labels,alternate)),'sizes':{str(i):int((labels==i).sum()) for i in range(k)}});models[k]=(model,labels)
    if not scores:raise ValueError('Not enough users to cluster')
    best=max(scores,key=lambda s:s['silhouette'] if s['silhouette'] is not None else -2)
    model,labels=models[best['k']];frame['cluster']=labels
    # A smaller ordinary K-Means timing comparison with identical standardized descriptors.
    t=time.perf_counter();ordinary=KMeans(n_clusters=best['k'],n_init=3,random_state=seed).fit(x[sample]);ordinary_seconds=time.perf_counter()-t
    out=Path(cfg['paths']['reports'])/'results';out.mkdir(parents=True,exist_ok=True)
    frame.to_csv(out/'assignments-users.csv',index=False)
    profiles=frame.drop(columns='user_key').groupby('cluster').mean();profiles.to_csv(out/'cluster_profiles.csv')
    pd.DataFrame(scaler.inverse_transform(model.cluster_centers_),columns=features).to_csv(out/'cluster_centroids.csv',index_label='cluster')
    result={'created_at':utcnow(),'synthetic':cfg['synthetic'],'scope':'full warehouse descriptive rating-active users; not predictive features','users':len(frame),'features':features,'seed':seed,'candidates':scores,'selected_k':best['k'],'selection_policy':'highest sampled silhouette; inspect stability, sizes and profiles before substantive interpretation','ordinary_kmeans':{'sample_users':len(sample),'seconds':ordinary_seconds,'inertia':float(ordinary.inertia_)}}
    atomic_json(out/'clustering.json',result)
    models_path=Path(cfg['paths']['models']);models_path.mkdir(parents=True,exist_ok=True)
    with (models_path/'clustering.pkl').open('wb') as f:pickle.dump({'imputer':imputer,'scaler':scaler,'model':model,'features':features},f)
    return result
