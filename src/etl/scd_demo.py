"""Recorded offline metadata refresh proof, isolated to the synthetic warehouse."""
import hashlib
import json
from pathlib import Path
from utils.common import atomic_json
from pipeline import run
from etl.load import connect


def demo(cfg):
    if not cfg.get('synthetic'):raise ValueError('SCD demo requires synthetic isolation')
    results=[]
    with connect(cfg) as con:
        # Explicit fixture setup permits repeating the A/B/C demonstration.
        con.execute("UPDATE DimMovie SET runtime=NULL,previous_runtime=NULL,original_language=NULL,previous_original_language=NULL,runtime_changed_at=NULL,language_changed_at=NULL,metadata_fetched_at=NULL WHERE tmdb_id=101")
        before=con.execute('SELECT count(*),bit_xor(hash(rating_event_id)) FROM FactRatings').fetchone()
        keys=con.execute('SELECT movie_id,movie_key FROM DimMovie ORDER BY movie_id').fetchall()
    for label,runtime in [('A',90),('B',90),('C',95)]:
        fetched=f'2026-10-0{1+len(results)}T00:00:00+00:00'
        payload={'id':101,'title':'Synthetic Film 1','runtime':runtime,'original_language':'en'}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        path=Path(cfg['paths']['raw_tmdb'])/f'demo-{label}'/'101-en-US.json'
        atomic_json(path,{'tmdb_id':101,'movie_ids':[1],'endpoint':'/movie/101','language':'en-US','fetched_at':fetched,'http_status':200,'run_id':'synthetic-'+label,'payload_hash':digest,'payload':payload,'synthetic':True})
        atomic_json(Path(cfg['paths']['state'])/'tmdb_manifest.json',{'101:en-US':{'tmdb_id':101,'language':'en-US','status':'success','snapshot':str(path),'fetched_at':fetched,'payload_hash':digest}})
        run(cfg,mode='incremental',offline=True)
        with connect(cfg,read_only=True) as con:
            assert before==con.execute('SELECT count(*),bit_xor(hash(rating_event_id)) FROM FactRatings').fetchone()
            assert keys==con.execute('SELECT movie_id,movie_key FROM DimMovie ORDER BY movie_id').fetchall()
            row=con.execute('SELECT runtime,previous_runtime,original_language,previous_original_language FROM DimMovie WHERE movie_id=1').fetchone()
            results.append({'run':label,'runtime':row[0],'previous_runtime':row[1],'language':row[2],'previous_language':row[3],'facts_and_keys_unchanged':True})
    assert results[0]['previous_runtime'] is None and results[1]['previous_runtime'] is None and results[2]['previous_runtime']==90
    atomic_json(Path(cfg['paths']['reports'])/'results'/'scd3_demo.json',{'synthetic':True,'fixture_metadata_initialized':True,'results':results})
    return results
