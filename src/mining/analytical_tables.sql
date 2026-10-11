CREATE OR REPLACE TABLE MovieMonthAggregate AS
SELECT movie_key,min(date_key) AS date_key,count(*)::BIGINT AS n,sum(rating) AS rating_sum
FROM FactRatings JOIN DimDate USING(date_key)
GROUP BY movie_key,year,month;
