import platform
import re
import statistics
import time
from pathlib import Path
import duckdb
from utils.common import atomic_json, utcnow, writer_lock
from etl.load import connect, ROOT


def benchmark(cfg, start_year=1995, end_year=2015, genres=None, min_support=100, repetitions=5):
    out = Path(cfg['paths']['reports'])/'results'
    out.mkdir(parents=True, exist_ok=True)
    params={'start_year':start_year,'end_year':end_year,'genres':genres or ['Drama','Comedy'],'min_support':min_support}
    queries=read_queries()
    results=[]; outputs={}
    with writer_lock(cfg['paths']['warehouse']), connect(cfg) as con:
        n=con.execute('SELECT count(*) FROM FactRatings').fetchone()[0]
        t=time.perf_counter(); con.execute('CREATE OR REPLACE TABLE MovieMonthAggregate AS SELECT movie_key,min(date_key) date_key,count(*)::BIGINT n,sum(rating) rating_sum FROM FactRatings JOIN DimDate USING(date_key) GROUP BY movie_key,year,month'); build=time.perf_counter()-t
        for variant in ['fact_scan','preaggregate']:
            source = 'SELECT movie_key,date_key,1::BIGINT n,rating rating_sum FROM FactRatings' if variant=='fact_scan' else 'SELECT * FROM MovieMonthAggregate'
            for number,sql in enumerate(queries,1):
                sql=render_query(sql, params, source)
                t=time.perf_counter(); frame=con.execute(sql).fetchdf(); warmup=time.perf_counter()-t
                timings=[]
                for _ in range(max(5,repetitions)):
                    t=time.perf_counter(); con.execute(sql).fetchall(); timings.append(time.perf_counter()-t)
                key=f'Q{number}'
                if variant=='fact_scan': outputs[key]=frame
                else:
                    # Same ordered groups; summation order may change the last floating point bits.
                    import pandas as pd
                    pd.testing.assert_frame_equal(outputs[key],frame,check_dtype=False,check_exact=False,rtol=1e-9,atol=1e-8)
                frame.to_csv(out/f'query-results-{key}-{variant}.csv',index=False)
                (out/f'{key}-{variant}-analyze.txt').write_text('\n'.join(str(r) for r in con.execute('EXPLAIN ANALYZE '+sql).fetchall()))
                results.append({'query':key,'variant':variant,'rows':len(frame),'warmup_seconds':warmup,'repetitions_seconds':timings,'median_seconds':statistics.median(timings),'min_seconds':min(timings),'max_seconds':max(timings),'std_seconds':statistics.pstdev(timings),'correctness':'baseline and aggregate agree'})
    record={'created_at':utcnow(),'synthetic':cfg['synthetic'],'ratings':n,'duckdb':duckdb.__version__,'platform':platform.platform(),'processor':platform.processor(),'cpu_count':__import__('os').cpu_count(),'container_memory_bytes':Path('/proc/meminfo').read_text().splitlines()[0] if Path('/proc/meminfo').exists() else None,'settings':cfg['warehouse'],'parameters':params,'cache':'warm repeated runs; no cold-cache claim','aggregate_build_seconds':build,'results':results}
    atomic_json(out/'olap.json',record)
    import pandas as pd
    pd.DataFrame([{k:v for k,v in r.items() if k!='repetitions_seconds'} for r in results]).to_csv(out/'olap.csv',index=False)
    return record


FACT_SOURCE = 'SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings'


def read_queries():
    """Five self-contained statements, also suitable for DuckDB UI."""
    return [s.strip() for s in re.split(r'-- Q\d\s*', (ROOT/'sql/olap_queries.sql').read_text()) if s.strip()]


def render_query(sql, params, source):
    sql = sql.replace(FACT_SOURCE, source)
    for name, default in [('start_year', 1995), ('end_year', 2015), ('min_support', 100)]:
        sql = sql.replace(f'{default} /* {name} */', str(int(params[name])))
    genres = '[' + ', '.join("'" + str(g).replace("'", "''") + "'" for g in params['genres']) + ']'
    return sql.replace("['Drama', 'Comedy'] /* genres */", genres)


from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from etl.load import connect
from utils.common import atomic_json,utcnow


def eda(cfg):
    out=Path(cfg['paths']['reports'])/'figures';out.mkdir(parents=True,exist_ok=True)
    result={'created_at':utcnow(),'synthetic':cfg['synthetic'],'charts':[]}
    with connect(cfg,read_only=True) as con:
        for name,sql,x,y in [
            ('rating_distribution','SELECT rating,count(*) AS events FROM FactRatings GROUP BY rating ORDER BY rating','rating','events'),
            ('annual_activity','SELECT year AS rating_year,count(*) AS events,avg(rating) AS average_rating FROM FactRatings JOIN DimDate USING(date_key) GROUP BY year ORDER BY year','rating_year','events'),
            ('allocated_genre_activity','SELECT genre_name,sum(allocation_weight) AS allocated_events FROM FactRatings JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key) GROUP BY genre_name ORDER BY allocated_events DESC','genre_name','allocated_events')]:
            frame=con.execute(sql).fetchdf();frame.to_csv(out/f'{name}.csv',index=False)
            fig,ax=plt.subplots(figsize=(10,5));ax.bar(frame[x].astype(str),frame[y]);ax.set(xlabel=x,ylabel=y,title=name.replace('_',' ').title());ax.tick_params(axis='x',rotation=70);fig.tight_layout();fig.savefig(out/f'{name}.png',dpi=160);plt.close(fig);result['charts'].append(name)
    atomic_json(out/'manifest.json',result)
    return result
