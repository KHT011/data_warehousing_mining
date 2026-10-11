from pathlib import Path
import pytest
from utils.config import load_config
from etl.synthetic import generate


def test_conservation_and_unchanged_keys(cfg):
    from pipeline import run
    from etl.load import connect, validate
    run(cfg, offline=True)
    import json
    quality_files=list((Path(cfg['paths']['reports'])/'quality').glob('20*.json'))
    quality=json.loads(quality_files[-1].read_text())
    assert (quality['raw_ratings'],quality['retained_ratings'],quality['removed_exact_duplicates'],quality['rejected_ratings'])==(1804,1800,1,3)
    with connect(cfg) as con:
        before = con.execute('SELECT movie_id,movie_key FROM DimMovie ORDER BY 1').fetchall()
        assert validate(con)['ratings'] == 1800
        assert con.execute('SELECT count(*) FROM DimUser').fetchone()[0] == 61
    run(cfg, offline=True)
    with connect(cfg) as con:
        assert before == con.execute('SELECT movie_id,movie_key FROM DimMovie ORDER BY 1').fetchall()
        assert validate(con)['ratings'] == 1800


def test_event_conflict_stops_publication(cfg):
    from pipeline import run
    with (Path(cfg['paths']['raw_movielens']) / 'ratings.csv').open('a') as f:
        f.write('1,1,0.5,1000000000\n1,1,5.0,1000000000\n')
    with pytest.raises(ValueError, match='conflict'):
        run(cfg, offline=True)
    assert not Path(cfg['paths']['warehouse']).exists()


def test_sql_scd3_incremental_preserves_facts(cfg):
    from pipeline import run
    from etl.load import connect, apply_metadata
    run(cfg, offline=True)
    with connect(cfg) as con:
        before = con.execute('SELECT count(*), min(rating_event_id),max(rating_event_id) FROM FactRatings').fetchone()
        apply_metadata(con, [{'id':101,'runtime':90,'original_language':'en','fetched_at':'2026-01-01T00:00:00Z'}])
        apply_metadata(con, [{'id':101,'runtime':90,'original_language':'en','fetched_at':'2026-01-02T00:00:00Z'}])
        apply_metadata(con, [{'id':101,'runtime':95,'original_language':'en','fetched_at':'2026-01-03T00:00:00Z'}])
        assert con.execute('SELECT runtime,previous_runtime,previous_original_language FROM DimMovie WHERE tmdb_id=101').fetchone() == (95,90,None)
        assert before == con.execute('SELECT count(*), min(rating_event_id),max(rating_event_id) FROM FactRatings').fetchone()


def test_malformed_csv_reaches_quarantine_and_reconciles(cfg):
    import json
    from pipeline import run
    with (Path(cfg['paths']['raw_movielens'])/'ratings.csv').open('a') as f:
        f.write('1,2,3.0,1000000005,extra\n')
    result=run(cfg,offline=True)
    quality=json.loads((Path(cfg['paths']['reports'])/'quality'/f"{result['run_id']}.json").read_text())
    assert quality['raw_ratings']==1805
    assert quality['retained_ratings']==1800
    assert quality['removed_exact_duplicates']==1
    assert quality['rejected_ratings']==4
    assert next(r for r in quality['rules'] if r['rule']=='malformed_csv')['rows_rejected']==1


from pathlib import Path
import pytest
from utils.common import checksum,read_json


def test_failed_candidate_preserves_published_warehouse(cfg,monkeypatch):
    from pipeline import run
    from etl import load as loader
    result=run(cfg,offline=True)
    path=Path(cfg['paths']['warehouse']);before=checksum(path)
    metrics=read_json(Path(cfg['paths']['reports'])/'quality'/f"{result['run_id']}.json")
    def reject(_):raise ValueError('Injected integrity failure')
    monkeypatch.setattr(loader,'validate',reject)
    with pytest.raises(ValueError,match='integrity'):
        loader.load(cfg,Path(metrics['stage']),metrics,[],'failed-publication')
    assert checksum(path)==before


from pathlib import Path
import pytest
from utils.common import atomic_json,checksum
from pipeline import reusable_stage


def test_resume_checks_source_fingerprints_and_reconciliation(cfg):
    root=Path(cfg['paths']['reports']);run='original'
    fingerprints={name:checksum(Path(cfg['paths']['raw_movielens'])/f'{name}.csv') for name in ['ratings','movies','links','tags']}
    atomic_json(root/'quality'/f'{run}.json',{'reconciliation':True,'source_sha256':fingerprints})
    atomic_json(root/'runs'/f'{run}.json',{'started_at':'2026-10-01'})
    atomic_json(Path(cfg['paths']['state'])/f'{run}-config.json',cfg)
    for name in fingerprints:
        p=Path(cfg['paths']['staging'])/run/name;p.mkdir(parents=True);(p/'part.parquet').write_bytes(b'fixture existence; load validates parquet')
    assert reusable_stage(cfg,run)[1]['reconciliation']
    with (Path(cfg['paths']['raw_movielens'])/'ratings.csv').open('a') as f:f.write('1,1,5,123\n')
    with pytest.raises(ValueError,match='fingerprint changed'):reusable_stage(cfg,run)


import subprocess
import sys
import pytest
from utils.common import writer_lock


def test_abruptly_stopped_owner_does_not_block_resume(tmp_path):
    path=tmp_path/'pipeline'
    child=subprocess.Popen([sys.executable,'-c',"from utils.common import writer_lock; import sys,time\nwith writer_lock(sys.argv[1]):\n print('locked',flush=True)\n time.sleep(60)",str(path)],stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='locked'
        with pytest.raises((RuntimeError,FileExistsError)):
            with writer_lock(path):pass
    finally:
        child.kill();child.wait(timeout=5)
    # Killing a container must release ownership without manual deletion.
    with writer_lock(path):pass

