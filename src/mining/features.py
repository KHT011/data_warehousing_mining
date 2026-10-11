import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from utils.common import atomic_json, utcnow
from etl.load import connect


def build_features(df, train_fraction=.70, validation_fraction=.15):
    df=df.sort_values(['timestamp','rating_event_id']).reset_index(drop=True).copy()
    if len(df)<10:
        raise ValueError('At least ten events needed for chronological evaluation')
    train_end=int(df.iloc[min(int(len(df)*train_fraction),len(df)-1)].timestamp)
    validation_end=int(df.iloc[min(int(len(df)*(train_fraction+validation_fraction)),len(df)-1)].timestamp)
    df['split']=np.where(df.timestamp<train_end,'train',np.where(df.timestamp<validation_end,'validation','test'))
    train=df[df.split=='train']
    if any((df.split==s).sum()==0 for s in ['train','validation','test']):
        raise ValueError('Timestamp ties leave an empty split')
    global_mean=float(train.rating.mean())
    # Leave-one-out approximation: row's own target excluded from each training statistic,
    # including the fallback. Not a strict earlier-event temporal feature.
    for key,prefix in [('user_key','user'),('movie_key','movie')]:
        ag=train.groupby(key).rating.agg(['sum','count'])
        count=df[key].map(ag['count']).fillna(0).astype(float)
        sums=df[key].map(ag['sum']).fillna(0)
        training=df.split=='train'
        sums=sums-training.astype(int)*df.rating
        count=count-training.astype(int)
        fallback=np.where(training,(train.rating.sum()-df.rating)/max(1,len(train)-1),global_mean)
        df[prefix+'_mean']=np.where(count>0,sums/count.replace(0,np.nan),fallback)
        df[prefix+'_count']=count
    dates=pd.to_datetime(df.timestamp,unit='s',utc=True)
    df['rating_year']=dates.dt.year; df['rating_month']=dates.dt.month; df['rating_weekday']=dates.dt.dayofweek
    df['movie_age']=df.rating_year-df.release_year
    # DuckDB nullable integers produce pd.NA comparisons. Unknown age remains
    # missing for train-only imputation and has its separate missing-year flag.
    df['negative_movie_age']=(df.movie_age<0).fillna(False).astype(int)
    df['release_year_missing']=df.release_year.isna().astype(int)
    # Multi-hot MovieLens genres are catalog descriptors, never contemporary TMDB engagement.
    genres=sorted({g for value in train.genre.fillna('Unknown') for g in value.split('|')})
    for genre in genres:
        df['genre_'+genre]=df.genre.fillna('Unknown').map(lambda v:int(genre in v.split('|')))
    features=['user_mean','movie_mean','user_count','movie_count','rating_year','rating_month','rating_weekday','release_year','movie_age','negative_movie_age','release_year_missing']+['genre_'+g for g in genres]
    manifest={'train_end':train_end,'validation_end':validation_end,'train_global_mean':global_mean,'features':features,'training_aggregate_policy':'leave-one-out target-excluding approximation; not strict temporal','heldout_policy':'training aggregates only; unseen keys use training global mean','excluded':['user_key as continuous feature','movie_key as continuous feature','popularity','vote_average','vote_count','tags'],'splits':{s:{'rows':int((df.split==s).sum()),'min_timestamp':int(df.loc[df.split==s,'timestamp'].min()),'max_timestamp':int(df.loc[df.split==s,'timestamp'].max())} for s in ['train','validation','test']}}
    return df,manifest


def prepare(cfg, limit=None):
    limit=int(limit or cfg['mining']['regression_sample_limit'])
    if limit<10: raise ValueError('sample limit must be >=10')
    seed=int(cfg['project']['seed'])
    with connect(cfg,read_only=True) as con:
        total=con.execute('SELECT count(*) FROM FactRatings').fetchone()[0]
        # Deterministic hash sample chosen before splitting; ORDER BY hash top-N uses bounded heap.
        frame=con.execute('''WITH chosen AS (SELECT * FROM FactRatings ORDER BY hash(rating_event_id || ?) LIMIT ?),
          catalog AS (SELECT movie_key,string_agg(genre_name,'|' ORDER BY genre_name) genre FROM BridgeMovieGenre JOIN DimGenre USING(genre_key) GROUP BY movie_key)
          SELECT f.rating_event_id,f.user_key,f.movie_key,f.rating,epoch(f.rating_timestamp)::BIGINT AS timestamp,m.release_year,c.genre
          FROM chosen f JOIN DimMovie m USING(movie_key) JOIN catalog c USING(movie_key)''',[str(seed),limit]).fetchdf()
        runs=con.execute('SELECT run_id FROM ETLRun ORDER BY finished_at').fetchall()
    frame,manifest=build_features(frame,cfg['mining']['train_fraction'],cfg['mining']['validation_fraction'])
    manifest.update(created_at=utcnow(),synthetic=cfg['synthetic'],seed=seed,source_ratings=total,sample_rows=len(frame),sample_policy='lowest deterministic DuckDB hash(event_id || seed), before split',source_run_ids=[r[0] for r in runs],code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    dest=Path(cfg['paths']['processed'])/'regression';dest.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(dest/'features.parquet',index=False)
    atomic_json(dest/'manifest.json',manifest)
    atomic_json(Path(cfg['paths']['reports'])/'results'/'feature_manifest.json',manifest)
    return manifest
