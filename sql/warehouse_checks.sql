SELECT 'orphan_users' AS rule,count(*) AS violations FROM FactRatings f ANTI JOIN DimUser u USING(user_key)
UNION ALL SELECT 'orphan_movies',count(*) FROM FactRatings f ANTI JOIN DimMovie m USING(movie_key)
UNION ALL SELECT 'orphan_dates',count(*) FROM FactRatings f ANTI JOIN DimDate d USING(date_key)
UNION ALL SELECT 'invalid_ratings',count(*) FROM FactRatings WHERE rating NOT BETWEEN 0.5 AND 5 OR rating*2<>floor(rating*2)
UNION ALL SELECT 'genre_weights',count(*) FROM (SELECT movie_key,sum(allocation_weight) w FROM BridgeMovieGenre GROUP BY movie_key HAVING abs(w-1)>1e-9)
UNION ALL SELECT 'movies_without_genres',count(*) FROM DimMovie ANTI JOIN BridgeMovieGenre USING(movie_key);
