# Bus matrix

| Process | User | Movie | UTC Date | Genre via weighted bridge | Degenerate ID |
|---|---|---|---|---|---|
| Rating event | Yes | Yes | Yes | Yes | SHA-256 user/movie/epoch |
| Metadata refresh | No | Updates Type 3 | Observed timestamp only | Separate TMDB genres | No |

Tags are audited and staged; tag-only participants enter DimUser. Tag-level warehouse analytics and tag-topic hypotheses are deferred, so no unused FactTags or DimTag is created.
