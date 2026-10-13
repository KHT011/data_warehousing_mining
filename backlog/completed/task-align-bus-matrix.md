# Align the repository bus matrix with the progress report

Status: Done

Scope: Align local warehouse documentation with Table 2 in the current progress report. Documentation only.

Acceptance criteria:
- [x] Match the report's rating-event and movie/month-summary rows and dimension columns.
- [x] Document both grains, aggregate measures, representative month date and genre access.
- [x] Describe metadata refresh separately as an ETL operation.
- [x] Check the matrix against the report and the actual aggregate construction SQL.

Verification on 13 October 2026:
- Compared all table cells with Table 2 read from the current native Google Doc in this chat; cells match after ignoring quotation/Markdown formatting around DimDate.
- Checked movie/year/month grouping, count and score-sum measures and minimum date key against src/analytics.py.
- Updated docs/schema.md to describe the same derived summary and link to the matrix.
- Whitespace check passed. No runtime tests were needed for this documentation change; warehouse data, code and benchmark results were not changed.
