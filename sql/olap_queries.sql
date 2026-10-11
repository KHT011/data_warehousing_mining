-- Q1
-- Roll-up: year → quarter → month
WITH activity AS (
 SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings
)
SELECT year AS rating_year,quarter,month,sum(n) AS rating_count,sum(rating_sum)/sum(n) AS average_rating
FROM activity JOIN DimDate USING(date_key)
GROUP BY ROLLUP(year,quarter,month) ORDER BY year NULLS LAST,quarter NULLS LAST,month NULLS LAST;

-- Q2
-- Cube: allocated genre and year totals
WITH activity AS (
 SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings
)
SELECT genre_name,year AS rating_year,sum(n*allocation_weight) AS allocated_count,sum(rating_sum*allocation_weight)/sum(n*allocation_weight) AS average_rating
FROM activity JOIN DimDate USING(date_key) JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key)
GROUP BY CUBE(genre_name,year) ORDER BY genre_name NULLS LAST,year NULLS LAST;

-- Q3
-- Slice/dice and drill-down: genres → years → months
WITH activity AS (
 SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings
)
SELECT genre_name,year AS rating_year,month,sum(n) AS overlapping_count,sum(rating_sum)/sum(n) AS average_rating
FROM activity JOIN DimDate USING(date_key) JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key)
WHERE genre_name IN (SELECT unnest(['Drama', 'Comedy'] /* genres */)) AND year BETWEEN 1995 /* start_year */ AND 2015 /* end_year */
GROUP BY GROUPING SETS ((genre_name,year),(genre_name,year,month)) ORDER BY genre_name,year,month NULLS FIRST;

-- Q4
-- Pivot: compare two years by genre
WITH activity AS (
 SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings
)
SELECT genre_name,
 sum(rating_sum) FILTER(WHERE year=1995 /* start_year */)/nullif(sum(n) FILTER(WHERE year=1995 /* start_year */),0) AS first_year_mean,
 sum(n) FILTER(WHERE year=1995 /* start_year */) AS first_year_count,
 sum(rating_sum) FILTER(WHERE year=2015 /* end_year */)/nullif(sum(n) FILTER(WHERE year=2015 /* end_year */),0) AS last_year_mean,
 sum(n) FILTER(WHERE year=2015 /* end_year */) AS last_year_count
FROM activity JOIN DimDate USING(date_key) JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key)
WHERE year IN (1995 /* start_year */,2015 /* end_year */) GROUP BY genre_name ORDER BY genre_name;

-- Q5
-- Window ranking: supported top movies per genre/year
WITH activity AS (
 SELECT movie_key,date_key,1::BIGINT AS n,rating AS rating_sum FROM FactRatings
),
summary AS (
 SELECT genre_name,year AS rating_year,m.movie_id,m.title,sum(n) AS support,sum(rating_sum)/sum(n) AS mean_rating
 FROM activity JOIN DimDate USING(date_key) JOIN DimMovie m USING(movie_key) JOIN BridgeMovieGenre USING(movie_key) JOIN DimGenre USING(genre_key)
 WHERE year BETWEEN 1995 /* start_year */ AND 2015 /* end_year */ GROUP BY ALL HAVING sum(n)>=100 /* min_support */
), ranked AS (SELECT *,dense_rank() OVER(PARTITION BY genre_name,rating_year ORDER BY mean_rating DESC) AS rank FROM summary)
SELECT * FROM ranked WHERE rank<=10 ORDER BY genre_name,rating_year,rank,movie_id;
