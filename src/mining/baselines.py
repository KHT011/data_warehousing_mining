import json
import pickle
import time
from pathlib import Path
import numpy as np
import pandas as pd
from utils.common import atomic_json, read_json, utcnow
from mining.evaluation import metrics


def fit_bias(train, regularization=10., iterations=10):
    mean=float(train.rating.mean()); users={}; movies={}
    for _ in range(iterations):
        residual=train.rating-mean-train.movie_key.map(movies).fillna(0)
        g=residual.groupby(train.user_key)
        users=(g.sum()/(g.count()+regularization)).to_dict()
        residual=train.rating-mean-train.user_key.map(users).fillna(0)
        g=residual.groupby(train.movie_key)
        movies=(g.sum()/(g.count()+regularization)).to_dict()
    return {'mean':mean,'users':users,'movies':movies,'regularization':regularization,'iterations':iterations}


def predict_bias(frame, model):
    return model['mean']+frame.user_key.map(model['users']).fillna(0).to_numpy()+frame.movie_key.map(model['movies']).fillna(0).to_numpy()


def run(cfg):
    source=Path(cfg['paths']['processed'])/'regression'
    frame=pd.read_parquet(source/'features.parquet'); manifest=read_json(source/'manifest.json')
    train=frame[frame.split=='train']; validation=frame[frame.split=='validation']; test=frame[frame.split=='test']
    started=time.perf_counter()
    # Tune the small, explicit regularization budget on validation only.
    candidates=[]
    for penalty in [5.,10.,25.]:
        model=fit_bias(train,penalty)
        candidates.append((metrics(validation.rating,predict_bias(validation,model))['rmse'],model))
    model=min(candidates,key=lambda r:r[0])[1]
    mean=np.full(len(test),model['mean']); bias=predict_bias(test,model)
    warm=test.user_key.isin(train.user_key)&test.movie_key.isin(train.movie_key)
    result={'created_at':utcnow(),'synthetic':cfg['synthetic'],'manifest':manifest,'training_seconds':time.perf_counter()-started,'regularization_budget':[5,10,25],'selected_regularization':model['regularization'],'global_mean':metrics(test.rating,mean),'bias_unclipped':metrics(test.rating,bias),'bias_clipped':metrics(test.rating,np.clip(bias,.5,5)),'warm_start':metrics(test.loc[warm,'rating'],bias[warm]),'cold_start':metrics(test.loc[~warm,'rating'],bias[~warm])}
    dest=Path(cfg['paths']['reports'])/'results';dest.mkdir(parents=True,exist_ok=True)
    atomic_json(dest/'baselines.json',result)
    frame=test[['rating_event_id','user_key','movie_key','rating']].copy();frame['mean_prediction']=mean;frame['bias_prediction']=bias
    frame.to_csv(dest/'predictions-baselines.csv',index=False)
    models=Path(cfg['paths']['models']);models.mkdir(parents=True,exist_ok=True)
    with (models/'bias.pkl').open('wb') as f:pickle.dump(model,f)
    return result
