import pickle
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from xgboost import XGBRegressor
from utils.common import read_json, atomic_json, utcnow
from mining.baselines import fit_bias,predict_bias
from mining.evaluation import metrics,paired_user_bootstrap


def run(cfg):
    source=Path(cfg['paths']['processed'])/'regression'
    frame=pd.read_parquet(source/'features.parquet');manifest=read_json(source/'manifest.json')
    train=frame[frame.split=='train'];val=frame[frame.split=='validation'];test=frame[frame.split=='test'];features=manifest['features']
    imputer=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)
    x=imputer.fit_transform(train[features]);v=imputer.transform(val[features]);xt=imputer.transform(test[features])
    candidates=[];t=time.perf_counter();budget=[]
    for depth in [4,6]:
        model=XGBRegressor(n_estimators=150,max_depth=depth,learning_rate=.05,subsample=.8,colsample_bytree=.8,objective='reg:squarederror',tree_method='hist',n_jobs=2,random_state=cfg['project']['seed'])
        ts=time.perf_counter();model.fit(x,train.rating);score=metrics(val.rating,model.predict(v))
        candidates.append((score['rmse'],model));budget.append({'max_depth':depth,'validation':score,'seconds':time.perf_counter()-ts})
    model=min(candidates,key=lambda r:r[0])[1];pred=model.predict(xt)
    baseline_record=read_json(Path(cfg['paths']['reports'])/'results'/'baselines.json',{})
    bias=fit_bias(train,baseline_record.get('selected_regularization',10.));bp=predict_bias(test,bias)
    warm=test.user_key.isin(train.user_key)&test.movie_key.isin(train.movie_key)
    parameters=model.get_params()
    # The estimator's default missing-value sentinel is NaN, which is not JSON.
    parameters.pop('missing',None)
    result={'created_at':utcnow(),'synthetic':cfg['synthetic'],'sample_rows':len(frame),'train_rows':len(train),'test_rows':len(test),'training_seconds':time.perf_counter()-t,'budget':budget,'selected_parameters':parameters,'missing_value_policy':'XGBoost default NaN sentinel; omitted from JSON parameters','features':features,'test_unclipped':metrics(test.rating,pred),'test_clipped':metrics(test.rating,np.clip(pred,.5,5)),'warm_start':metrics(test.loc[warm,'rating'],pred[warm]),'cold_start':metrics(test.loc[~warm,'rating'],pred[~warm]),'uncertainty':paired_user_bootstrap(test,bp,pred,cfg['project']['seed'])}
    models=Path(cfg['paths']['models']);models.mkdir(parents=True,exist_ok=True)
    model.save_model(models/'xgboost.json')
    with (models/'imputer.pkl').open('wb') as f:pickle.dump(imputer,f)
    out=Path(cfg['paths']['reports'])/'results';out.mkdir(parents=True,exist_ok=True)
    atomic_json(out/'regression.json',result)
    predframe=test[['rating_event_id','user_key','rating']].copy();predframe['prediction']=pred;predframe.to_csv(out/'predictions-xgboost.csv',index=False)
    pd.DataFrame({'feature':imputer.get_feature_names_out(features),'importance':model.feature_importances_}).sort_values('importance',ascending=False).to_csv(out/'feature_importance.csv',index=False)
    return result
