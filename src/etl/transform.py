from pathlib import Path
from pyspark.sql import SparkSession, functions as F, types as T
from etl.extract import validate_sources
from utils.common import atomic_json, utcnow


def transform(cfg, run_id):
    root = validate_sources(cfg)
    stage = Path(cfg['paths']['staging']) / '.work' / run_id
    spark = (SparkSession.builder.master(cfg['spark']['master']).appName('MovieLensETL')
             .config('spark.sql.session.timeZone','UTC')
             .config('spark.sql.shuffle.partitions',str(cfg['spark']['shuffle_partitions']))
             .config('spark.driver.memory',cfg['spark']['driver_memory']).getOrCreate())
    spark.sparkContext.setLogLevel('WARN')
    metrics = {'run_id':run_id,'created_at':utcnow(),'synthetic':cfg['synthetic'],'rules':[]}
    def read(name, fields):
        # Parse strings explicitly first so malformed values remain inspectable in quarantine.
        schema = T.StructType([T.StructField(x,T.StringType()) for x in fields] + [T.StructField('_corrupt_record',T.StringType())])
        return spark.read.option('header',True).option('mode','PERMISSIVE').schema(schema).csv(str(root / f'{name}.csv'))
    def save(df, name):
        df.write.mode('overwrite').parquet(str(stage / (name + '.parquet')))
    try:
        movies = read('movies',['movieId','title','genres']).withColumn('movie_id',F.col('movieId').cast('int'))
        if movies.filter('movie_id IS NULL OR movie_id <= 0 OR title IS NULL OR _corrupt_record IS NOT NULL').count():
            raise ValueError('Critical movie schema violation')
        if movies.groupBy('movie_id').count().filter('count>1').count():
            raise ValueError('Duplicate movie natural key')
        movies = (movies.select('movie_id',F.col('title').alias('source_title'),'genres')
                  .withColumn('release_year',F.regexp_extract('source_title',r'\((\d{4})\)$',1).cast('int'))
                  .withColumn('title',F.trim(F.regexp_replace('source_title',r'\s*\(\d{4}\)$',''))))
        save(movies,'movies')
        links = read('links',['movieId','imdbId','tmdbId']).select(F.col('movieId').cast('int').alias('movie_id'),F.concat(F.lit('tt'),F.col('imdbId')).alias('imdb_id'),F.col('tmdbId').cast('int').alias('tmdb_id'))
        if links.groupBy('movie_id').count().filter('count>1').count():
            raise ValueError('Duplicate links mapping: explicit resolution required')
        if links.filter('movie_id IS NULL OR movie_id<=0').count():
            raise ValueError('Invalid links movie key')
        links = links.withColumn('tmdb_id',F.when(F.col('tmdb_id')>0,F.col('tmdb_id')))
        save(links,'links')
        # API metadata follows the same Parquet boundary as MovieLens data.
        import json
        from utils.common import read_json
        job = read_json(Path(cfg['paths']['state']) / f'{run_id}-job.json', {})
        columns = ['tmdb_id', 'runtime', 'original_language', 'title', 'release_date',
                   'genres', 'popularity', 'vote_average', 'vote_count', 'fetched_at', 'payload_hash']
        rows = []
        for payload in job.get('payloads', []):
            values = [payload['id'], payload.get('runtime'), payload.get('original_language'),
                      payload.get('title'), payload.get('release_date') or None,
                      json.dumps(payload.get('genres', [])), payload.get('popularity'),
                      payload.get('vote_average'), payload.get('vote_count'),
                      payload['fetched_at'], payload.get('payload_hash')]
            rows.append(tuple(None if value is None else str(value) for value in values))
        metadata = spark.createDataFrame(rows, T.StructType([T.StructField(name, T.StringType()) for name in columns]))
        for name, kind in [('tmdb_id', 'int'), ('runtime', 'int'), ('release_date', 'date'),
                           ('popularity', 'double'), ('vote_average', 'double'),
                           ('vote_count', 'long'), ('fetched_at', 'timestamp')]:
            metadata = metadata.withColumn(name, F.col(name).cast(kind))
        save(metadata, 'tmdb_movies')
        raw = read('ratings',['userId','movieId','rating','timestamp']).cache()
        raw_count = raw.count()
        parsed = (raw.withColumn('user_id',F.col('userId').cast('int')).withColumn('movie_id',F.col('movieId').cast('int'))
                  .withColumn('score',F.col('rating').cast('double')).withColumn('epoch',F.col('timestamp').cast('long'))
                  .join(movies.select('movie_id').withColumn('movie_exists',F.lit(True)), 'movie_id','left'))
        # First failing rule wins, so rejected categories are disjoint.
        reason = (F.when(F.col('_corrupt_record').isNotNull(),'malformed_csv')
                  .when(F.col('user_id').isNull() | (F.col('user_id')<=0) | F.col('movie_id').isNull() | (F.col('movie_id')<=0) | ~F.col('userId').rlike(r'^\d+$') | ~F.col('movieId').rlike(r'^\d+$'),'invalid_id')
                  .when(F.col('epoch').isNull() | (F.col('epoch')<0) | (F.col('epoch')>253402300799) | ~F.col('timestamp').rlike(r'^\d+$'),'invalid_timestamp')
                  .when(F.col('score').isNull() | F.isnan('score') | ~F.col('score').between(.5,5) | ((F.col('score')*2)%1!=0),'invalid_rating')
                  .when(F.col('movie_exists').isNull(),'orphan_movie'))
        parsed = parsed.withColumn('rejection_reason',reason).cache()
        rejected = parsed.filter('rejection_reason IS NOT NULL')
        save(rejected,'quarantine/ratings')
        rejected_by_rule={row[0]:row[1] for row in rejected.groupBy('rejection_reason').count().collect()}
        for rule in ['malformed_csv','invalid_id','invalid_timestamp','invalid_rating','orphan_movie']:
            count=rejected_by_rule.get(rule,0)
            metrics['rules'].append({'rule':rule,'severity':'error','rows_checked':raw_count,'rows_rejected':count, 'rows_passed':raw_count-count, 'samples':[r.asDict() for r in rejected.filter(F.col('rejection_reason')==rule).select('userId','movieId','timestamp').limit(5).collect()] if count else []})
        valid = parsed.filter('rejection_reason IS NULL').select('user_id','movie_id',F.col('score').alias('rating'),F.col('epoch').alias('timestamp')).cache()
        unique = valid.dropDuplicates().cache()
        conflicts = unique.groupBy('user_id','movie_id','timestamp').count().filter('count>1').count()
        if conflicts:
            atomic_json(Path(cfg['paths']['reports'])/'quality'/f'{run_id}.json',{'run_id':run_id,'conflicting_events':conflicts,'status':'rejected'})
            raise ValueError(f'{conflicts} conflicting rating event identities; publication stopped')
        retained = unique.count(); duplicates = valid.count()-retained
        rejected_count = rejected.count()
        assert raw_count == retained+duplicates+rejected_count
        cleaned = (unique.withColumn('rating_event_id',F.sha2(F.concat_ws(':','user_id','movie_id','timestamp'),256))
                   .withColumn('rating_timestamp',F.timestamp_seconds('timestamp'))
                   .withColumn('date_key',F.date_format('rating_timestamp','yyyyMMdd').cast('int')))
        save(cleaned,'ratings')
        tags_raw = read('tags',['userId','movieId','tag','timestamp'])
        tags = (tags_raw.withColumn('user_id',F.col('userId').cast('int')).withColumn('movie_id',F.col('movieId').cast('int'))
                .withColumn('epoch',F.col('timestamp').cast('long')).withColumn('source_tag',F.col('tag')).withColumn('tag',F.trim('tag')))
        good_tags = tags.filter('user_id>0 AND movie_id>0 AND epoch>=0 AND epoch<=253402300799 AND tag IS NOT NULL AND length(tag)>0 AND _corrupt_record IS NULL').join(movies.select('movie_id'),'movie_id','left_semi')
        save(good_tags.select('user_id','movie_id','source_tag','tag',F.col('epoch').alias('timestamp')).dropDuplicates(),'tags')
        metrics.update(raw_ratings=raw_count,retained_ratings=retained,removed_exact_duplicates=duplicates,rejected_ratings=rejected_count,conflicting_events=conflicts,raw_tags=tags_raw.count(),retained_tags=good_tags.dropDuplicates().count(),reconciliation=True)
        atomic_json(Path(cfg['paths']['reports'])/'quality'/f'{run_id}.json',metrics)
        import csv
        with (Path(cfg['paths']['reports'])/'quality'/f'{run_id}.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['rule','severity','rows_checked','rows_passed','rows_rejected'])
            writer.writeheader();writer.writerows({k:row[k] for k in writer.fieldnames} for row in metrics['rules'])
        return stage, metrics
    finally:
        spark.stop()


if __name__=='__main__':
    import json,sys
    transform(json.loads(Path(sys.argv[1]).read_text()),sys.argv[2])
