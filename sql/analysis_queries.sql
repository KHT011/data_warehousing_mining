-- Warehouse size and table grain.
SELECT 'ratings' AS entity, count(*) AS rows FROM FactRatings
UNION ALL SELECT 'movies', count(*) FROM DimMovie
UNION ALL SELECT 'users (including tag-only users)', count(*) FROM DimUser;

-- Ratings joined to their dimensions.
SELECT u.user_id, m.title, d.date, f.rating, f.rating_event_id
FROM FactRatings f JOIN DimUser u USING (user_key)
JOIN DimMovie m USING (movie_key) JOIN DimDate d USING (date_key)
ORDER BY d.date DESC LIMIT 100;

-- Type 3 history: current and previous metadata values.
SELECT movie_id, title, runtime, previous_runtime, runtime_changed_at,
       original_language, previous_original_language, language_changed_at,
       enrichment_status, metadata_fetched_at
FROM DimMovie ORDER BY movie_id LIMIT 100;

-- Provenance and successful loads.
SELECT * FROM ETLRun ORDER BY finished_at DESC LIMIT 20;

-- Genre weights must sum to one per movie.
SELECT movie_key, sum(allocation_weight) AS total_weight
FROM BridgeMovieGenre GROUP BY movie_key
HAVING abs(sum(allocation_weight) - 1.0) > 0.00000001;
