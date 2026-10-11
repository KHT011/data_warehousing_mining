CREATE SEQUENCE user_seq START 1;
CREATE SEQUENCE movie_seq START 1;
CREATE SEQUENCE genre_seq START 1;
CREATE TABLE DimUser(user_key BIGINT PRIMARY KEY DEFAULT nextval('user_seq'), user_id INTEGER UNIQUE NOT NULL CHECK(user_id>0));
CREATE TABLE DimMovie(
 movie_key BIGINT PRIMARY KEY DEFAULT nextval('movie_seq'), movie_id INTEGER UNIQUE NOT NULL,
 source_title VARCHAR NOT NULL,title VARCHAR,release_year INTEGER,imdb_id VARCHAR,tmdb_id INTEGER,
 tmdb_title VARCHAR,tmdb_release_date DATE,tmdb_genres VARCHAR,
 runtime INTEGER,previous_runtime INTEGER,original_language VARCHAR,previous_original_language VARCHAR,
 runtime_changed_at TIMESTAMPTZ,language_changed_at TIMESTAMPTZ,metadata_fetched_at TIMESTAMPTZ,
 enrichment_status VARCHAR DEFAULT 'unenriched',metadata_hash VARCHAR,
 popularity DOUBLE,vote_average DOUBLE,vote_count BIGINT
);
CREATE TABLE DimDate(date_key INTEGER PRIMARY KEY,date DATE UNIQUE,year INTEGER,quarter INTEGER,month INTEGER,month_name VARCHAR,day INTEGER,weekday INTEGER);
CREATE TABLE DimGenre(genre_key BIGINT PRIMARY KEY DEFAULT nextval('genre_seq'),genre_name VARCHAR UNIQUE NOT NULL);
CREATE TABLE BridgeMovieGenre(movie_key BIGINT REFERENCES DimMovie(movie_key),genre_key BIGINT REFERENCES DimGenre(genre_key),allocation_weight DOUBLE CHECK(allocation_weight>0 AND allocation_weight<=1),PRIMARY KEY(movie_key,genre_key));
CREATE TABLE FactRatings(rating_event_id VARCHAR PRIMARY KEY,user_key BIGINT REFERENCES DimUser(user_key),movie_key BIGINT REFERENCES DimMovie(movie_key),date_key INTEGER REFERENCES DimDate(date_key),rating DOUBLE NOT NULL CHECK(rating BETWEEN 0.5 AND 5 AND rating*2=floor(rating*2)),rating_timestamp TIMESTAMP NOT NULL);
CREATE TABLE ETLRun(run_id VARCHAR PRIMARY KEY,mode VARCHAR,started_at TIMESTAMPTZ,finished_at TIMESTAMPTZ,status VARCHAR,source_counts JSON,loaded_counts JSON);
