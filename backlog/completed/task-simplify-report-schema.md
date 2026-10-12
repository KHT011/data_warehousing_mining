# Simplify report schema diagram

## Scope
Redraw the current core rating schema with readable relationships and selected fields. Remove technical run history, the derived summary and long notes from this presentation diagram. Replace only Figure 2 and its caption in the existing Google Doc; refresh the saved PDF.

## Acceptance criteria
- Keep FactRatings, DimUser, DimMovie, DimDate, BridgeMovieGenre and DimGenre.
- Preserve all five declared relationships; no direct FactRatings-to-DimGenre link.
- Use simple connectors without crossings, extra arrows or technical notes.
- Label the diagram as a core schema with selected fields, rather than a complete physical ERD.
- Inspect the generated diagram and the report PDF after replacement.
- Preserve the full physical schema artifact and all report results.

## Completed
- Used built-in image editing to redraw the supplied diagram.
- Saved core_schema.png and the exact prompt under reports/progress_20261012/.
- Visually checked all six table names, displayed field names and all five 1:N connections.
- Replaced only Figure 2 and its caption in the Google Doc.
- Native readback still has eight tables and seven images.
- Exported the updated PDF: seven pages. Rendered and inspected page 2; no crossed lines or clipped labels.
- Original full_erd.png and warehouse/schema.sql are preserved.
