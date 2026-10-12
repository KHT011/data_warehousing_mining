# Clean pipeline figure

## Scope
Redraw Figure 1 to remove overlapping text and improve spacing. Preserve the actual pipeline flow. Replace Figure 1 in the existing Google Doc and refresh the saved PDF.

## Acceptance criteria
- Keep MovieLens and TMDb as inputs to PySpark/Parquet staging, followed by DuckDB and the two analysis outputs.
- Use short labels, clear arrows, and readable gaps between headings and descriptions.
- Do not suggest Airflow currently runs mining or a daily schedule.
- Preserve report results and all other figures.
- Inspect the generated image, native document and changed PDF page.

## Completed
- Redrew the supplied pipeline image using built-in image editing.
- Shortened descriptions and separated them from headings; inspected all six boxes and five arrows.
- Saved pipeline_clean.png and the exact prompt in reports/progress_20261012/.
- Replaced only Figure 1 in the Google Doc; preserved all eight tables and seven images.
- Updated the saved PDF. It remains seven pages; rendered page 1 shows no overlap or clipping.
- Original pipeline.png is preserved.
