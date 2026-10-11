from etl.load import connect
from mining.scaling import run


def test_scaling_executes_real_sampling_sql_and_records_measured_rows(cfg):
    # Small real DuckDB catalog exercises the SQL parser and feature/model path.
    with connect(cfg) as con:
        con.execute("CREATE TABLE DimMovie AS SELECT 1 movie_key,1990 release_year")
        con.execute("CREATE TABLE DimGenre AS SELECT 1 genre_key,'Drama' genre_name")
        con.execute('CREATE TABLE BridgeMovieGenre AS SELECT 1 movie_key,1 genre_key')
        con.execute("""CREATE TABLE FactRatings AS SELECT i::VARCHAR rating_event_id,
            (i%5)::BIGINT user_key,1 movie_key,(0.5+(i%10)*0.5)::DOUBLE rating,
            to_timestamp(1000000000+i*3600) rating_timestamp FROM range(100) t(i)""")
    result=run(cfg,limit=100)
    assert result['results'][0]['sample_rows']==100
    assert result['results'][0]['train_rows']==70
    assert result['results'][0]['fit_seconds']>0
