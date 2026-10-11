import time
from pathlib import Path
import pandas as pd
from sklearn.impute import SimpleImputer
from xgboost import XGBRegressor
from utils.common import atomic_json,utcnow
from etl.load import connect
from mining.features import build_features


def run(cfg,limit=None):
    max_size=int(limit or cfg['mining']['regression_sample_limit'])
    sizes=sorted(set(min(max_size,n) for n in [100000,500000,1000000]))
    results=[]
    for size in sizes:
        t=time.perf_counter()
        with connect(cfg,read_only=True) as con:
            frame=con.execute('''WITH catalog AS (SELECT movie_key,string_agg(genre_name,'|' ORDER BY genre_name) genre FROM BridgeMovieGenre JOIN DimGenre USING(genre_key) GROUP BY movie_key)
            SELECT rating_event_id,user_key,movie_key,rating,epoch(rating_timestamp)::BIGINT AS timestamp,release_year,genre FROM FactRatings JOIN DimMovie USING(movie_key) JOIN catalog USING(movie_key) ORDER BY hash(rating_event_id || ?) LIMIT ?''',[str(cfg['project']['seed']),size]).fetchdf()
        features,manifest=build_features(frame,cfg['mining']['train_fraction'],cfg['mining']['validation_fraction']);preparation=time.perf_counter()-t
        train=features[features.split=='train'];imputer=SimpleImputer(strategy='median',keep_empty_features=True)
        t=time.perf_counter();x=imputer.fit_transform(train[manifest['features']])
        model=XGBRegressor(n_estimators=100,max_depth=4,tree_method='hist',n_jobs=2,random_state=cfg['project']['seed']);model.fit(x,train.rating)
        seconds=time.perf_counter()-t
        results.append({'sample_rows':len(features),'train_rows':len(train),'preparation_seconds':preparation,'fit_seconds':seconds,'training_rows_per_second':len(train)/seconds})
    out=Path(cfg['paths']['reports'])/'results';out.mkdir(parents=True,exist_ok=True)
    record={'created_at':utcnow(),'synthetic':cfg['synthetic'],'settings':{'n_estimators':100,'max_depth':4,'threads':2,'seed':cfg['project']['seed']},'results':results}
    atomic_json(out/'scaling.json',record);pd.DataFrame(results).to_csv(out/'scaling.csv',index=False)
    return record
