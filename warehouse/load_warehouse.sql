-- Dimension and fact loading from cleaned staging views.
INSERT INTO DimUser(user_id)
 SELECT user_id FROM (SELECT user_id FROM stage_ratings UNION SELECT user_id FROM stage_tags)
 WHERE user_id NOT IN (SELECT user_id FROM DimUser) ORDER BY user_id;
INSERT INTO DimMovie(movie_id,source_title,title,release_year,imdb_id,tmdb_id)
 SELECT m.movie_id,m.source_title,m.title,m.release_year,l.imdb_id,l.tmdb_id
 FROM stage_movies m LEFT JOIN stage_links l USING(movie_id)
 WHERE m.movie_id NOT IN (SELECT movie_id FROM DimMovie) ORDER BY m.movie_id;
CREATE TEMP TABLE genre_mapping AS
 SELECT DISTINCT movie_key, CASE WHEN genre IS NULL OR genre='' OR genre='(no genres listed)' THEN 'Unknown' ELSE genre END genre_name
 FROM stage_movies s JOIN DimMovie m USING(movie_id),unnest(string_split(coalesce(s.genres,'Unknown'),'|')) t(genre);
INSERT INTO DimGenre(genre_name) SELECT DISTINCT genre_name FROM genre_mapping WHERE genre_name NOT IN (SELECT genre_name FROM DimGenre) ORDER BY genre_name;
INSERT INTO BridgeMovieGenre SELECT movie_key,genre_key,1.0/count(*) OVER(PARTITION BY movie_key)
 FROM genre_mapping JOIN DimGenre USING(genre_name);
INSERT INTO DimDate
 SELECT DISTINCT date_key,cast(rating_timestamp AS DATE),year(rating_timestamp),quarter(rating_timestamp),month(rating_timestamp),monthname(rating_timestamp),day(rating_timestamp),isodow(rating_timestamp)
 FROM stage_ratings WHERE date_key NOT IN (SELECT date_key FROM DimDate);

INSERT INTO FactRatings SELECT rating_event_id,user_key,movie_key,date_key,rating,rating_timestamp
 FROM stage_ratings JOIN DimUser USING(user_id) JOIN DimMovie USING(movie_id)
 ORDER BY date_key,movie_key,user_key;

-- SCD TYPE 3
UPDATE DimMovie AS m SET
 previous_runtime=CASE WHEN m.metadata_fetched_at IS NOT NULL AND m.runtime IS DISTINCT FROM s.runtime THEN m.runtime ELSE m.previous_runtime END,
 previous_original_language=CASE WHEN m.metadata_fetched_at IS NOT NULL AND m.original_language IS DISTINCT FROM s.original_language THEN m.original_language ELSE m.previous_original_language END,
 runtime_changed_at=CASE WHEN m.metadata_fetched_at IS NOT NULL AND m.runtime IS DISTINCT FROM s.runtime THEN s.fetched_at ELSE m.runtime_changed_at END,
 language_changed_at=CASE WHEN m.metadata_fetched_at IS NOT NULL AND m.original_language IS DISTINCT FROM s.original_language THEN s.fetched_at ELSE m.language_changed_at END,
 runtime=s.runtime,original_language=s.original_language,
 tmdb_title=s.title,tmdb_release_date=s.release_date,tmdb_genres=s.genres,
 popularity=s.popularity,vote_average=s.vote_average,vote_count=s.vote_count,
 metadata_fetched_at=s.fetched_at,metadata_hash=s.payload_hash,enrichment_status='enriched'
FROM incoming_metadata s WHERE m.tmdb_id=s.tmdb_id
 AND (m.metadata_fetched_at IS NULL OR s.fetched_at>m.metadata_fetched_at);
