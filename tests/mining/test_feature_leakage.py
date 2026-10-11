import numpy as np
import pandas as pd
from mining.features import build_features


def rows():
    return pd.DataFrame({'rating_event_id':[str(i) for i in range(100)],'user_key':[i%5 for i in range(100)],'movie_key':[i%7 for i in range(100)],'rating':[1.+i%5 for i in range(100)],'timestamp':np.arange(100),'release_year':[1990]*100,'genre':['Drama']*100})


def test_heldout_labels_never_change_features():
    df=rows(); a,manifest=build_features(df)
    changed=df.copy(); changed.loc[changed.timestamp>=manifest['train_end'],'rating']=.5
    b,_=build_features(changed)
    columns=['user_mean','movie_mean','user_count','movie_count']
    pd.testing.assert_frame_equal(a[columns],b[columns])


def test_training_target_excluded_and_ties_kept_together():
    df=rows(); df.loc[69:72,'timestamp']=70
    a,m=build_features(df)
    assert a.groupby('timestamp')['split'].nunique().max()==1
    changed=df.copy(); changed.loc[1,'rating']=.5
    b,_=build_features(changed)
    assert a.loc[1,'user_mean']==b.loc[1,'user_mean']
    assert a.loc[1,'movie_mean']==b.loc[1,'movie_mean']
    assert 'vote_average' not in m['features']


def test_nullable_catalog_year_preserves_unknown_age():
    df=rows()
    df['release_year']=df.release_year.astype('Int32')
    df.loc[0,'release_year']=pd.NA
    df.loc[1,'release_year']=2020
    frame,_=build_features(df)
    assert pd.isna(frame.loc[0,'movie_age'])
    assert frame.loc[0,'release_year_missing']==1
    assert frame.loc[0,'negative_movie_age']==0
    assert frame.loc[1,'negative_movie_age']==1
