import json
from pathlib import Path
import pandas as pd
from utils.common import atomic_json
from mining.features import build_features
from mining.regression import run


def test_model_parameters_and_metrics_are_strict_json(cfg):
    frame=pd.DataFrame({'rating_event_id':[str(i) for i in range(100)],'user_key':[i%5 for i in range(100)],'movie_key':[i%7 for i in range(100)],'rating':[.5+(i%10)/2 for i in range(100)],'timestamp':list(range(100)),'release_year':[1990]*100,'genre':['Drama']*100})
    frame,manifest=build_features(frame)
    dest=Path(cfg['paths']['processed'])/'regression';dest.mkdir(parents=True)
    frame.to_parquet(dest/'features.parquet');atomic_json(dest/'manifest.json',manifest)
    result=run(cfg)
    encoded=(Path(cfg['paths']['reports'])/'results'/'regression.json').read_text()
    def reject_non_json_number(value):raise ValueError(value)
    assert json.loads(encoded,parse_constant=reject_non_json_number)['test_unclipped']['n']==15
    assert result['test_unclipped']['rmse']>=0
