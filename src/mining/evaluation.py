import numpy as np


def metrics(y, prediction):
    y=np.asarray(y,dtype=float); prediction=np.asarray(prediction,dtype=float)
    if len(y)==0: return {'n':0,'rmse':None,'mae':None}
    error=prediction-y
    return {'n':len(y),'rmse':float(np.sqrt(np.mean(error**2))),'mae':float(np.mean(abs(error)))}


def paired_user_bootstrap(frame, first, second, seed=42, repetitions=200):
    """User-block resampling of paired MSE difference, not iid event resampling."""
    import pandas as pd
    rows=pd.DataFrame({'user':frame.user_key,'delta':(np.asarray(first)-frame.rating.to_numpy())**2-(np.asarray(second)-frame.rating.to_numpy())**2})
    groups=rows.groupby('user').delta.agg(['sum','count']).to_numpy()
    rng=np.random.default_rng(seed); differences=[]
    for _ in range(repetitions):
        sample=groups[rng.integers(0,len(groups),len(groups))]
        differences.append(float(sample[:,0].sum()/sample[:,1].sum()))
    return {'method':'paired user-block bootstrap MSE(first)-MSE(second)','repetitions':repetitions,'seed':seed,'mean_delta_mse':float(rows.delta.mean()),'percentile_95_interval':np.quantile(differences,[.025,.975]).tolist()}
