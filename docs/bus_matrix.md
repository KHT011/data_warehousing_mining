# Bus matrix

| Process | User | Movie | Date | Genre | Event ID |
|---|---|---|---|---|---|
| Rating event | Yes | Yes | UTC date | Via bridge | Hash |
| Movie/month summary | No | Yes | Month through `DimDate` | Via bridge when querying | No |

This matrix matches Table 2 in the progress report and describes the two
analytical datasets compared in the OLAP benchmark.

- **Rating event (`FactRatings`):** one row per user, movie and original UTC
  timestamp. The event ID is a SHA-256 hash of those source values, stored
  directly in the fact as a technical degenerate identifier.
- **Movie/month summary (`MovieMonthAggregate`):** one row per movie, rating
  year and month, with a rating count and score sum. Individual users and
  rating-event IDs are aggregated away. The benchmark creates this derived
  table from `FactRatings`.
- **Date:** the summary stores the earliest rating date key in each movie/month
  group to join `DimDate` for year, quarter and month. That representative date
  does not preserve daily detail.
- **Genre:** both datasets retain movie keys, so queries connect to genres
  through `BridgeMovieGenre`. Allocation weights support non-duplicated
  overall totals; queries using overlapping genre membership label it explicitly.

Metadata refresh is an ETL operation that updates movie descriptions, including
Type 3 runtime/language history. It is documented separately in
[the schema](schema.md), rather than treated as another analytical fact here.
It does not create new MovieLens ratings.

Tags are audited and staged; tag-only participants enter DimUser. Tag-level warehouse analytics and tag-topic hypotheses are deferred, so no unused FactTags or DimTag is created.
