# Synthetic Healthcare Case Dataset

Files:

- `careflow_north.csv`
- `meditrack_east.csv`

## Design goals

- Preserve a two-system comparison with clearly different data quality profiles.
- Keep one source structurally stable and easy to parse.
- Give the second source realistic ingestion friction: mixed date formats, missing values, duplicates, and logical inconsistencies.
- Provide enough shared concepts to support cross-system KPI discussion without pretending the systems are fully identical.

## Source profiles

`careflow_north.csv`

- Uses stable `YYYYMMDD` date fields.
- Has high completeness and consistent field semantics.
- Covers January to November 2022 only, so December is intentionally absent.
- Includes `DT_CREATED` as an administrative system timestamp that can predate the 2022 study window.
- Includes a small unresolved backlog, so the clean system is not unrealistically perfect.
- Uses category-level cancellation patterns across `TRACK`, so some pathways are consistently lower-risk and others higher-risk.
- Uses deliberately uneven `TRACK` volumes, so a few pathways dominate while others stay noticeably smaller.
- Uses category-level treatment-time spread patterns, so some pathways are more standardized while others are more variable.

`meditrack_east.csv`

- Mixes `dd-mm-yyyy HH:MM` and `M/D/YYYY h:mm:ss AM/PM` style timestamps.
- Includes missing date values, date-order problems, and duplicate case identifiers.
- Covers all twelve months of 2022.
- Uses category-level cancellation patterns across `CareGroup` with a similar low-to-high gradient as the clean system.
- Uses deliberately uneven `CareGroup` volumes with a comparable large/mid/small pattern rather than near-uniform group sizes.
- Uses category-level treatment-time spread patterns that overlap with the clean system instead of separating the two datasets into distinct spread bands.

## Conceptual mapping

- `CARE_REF` <-> `RefNo`
- `DT_CREATED` <-> no direct cross-system equivalent; administrative timestamp only
- `DT_REG` <-> `RegisteredAt`
- `DT_ALLOC` <-> `AssignedOn`
- `DT_ABORT` <-> `CancelledOn`
- `DT_OPEN` <-> `StartPathway`
- `max(DT_END, DT_CLOSE)` <-> `FinishedAt`
- `ZIP_PAT` <-> `PostalArea`
- `TRACK` <-> `CareGroup`
- `UNIT_CODE` <-> `ClinicTag`

## Duplicate design

Duplicates are only present in `meditrack_east.csv`, and they appear in two forms:

- normalized full-row duplicates, where the entire record is repeated
- case-level duplicates, where the same `RefNo` appears more than once with overlapping content

The final analysis treats `RefNo` as the case identifier and collapses remaining duplicate case rows after parsing. That keeps case counts and KPI percentages aligned with the intended analytical grain.

## Geography

Postal codes are now assigned from explicit real-world postcode pools rather than made-up postcode ranges.

- `careflow_north.csv` is concentrated in Region Hovedstaden postcodes.
- `meditrack_east.csv` is concentrated in Region Sjælland postcodes.
- a small number of postcode assignments intentionally overlap across the two systems to mimic referrals, data-entry mistakes, and cross-boundary edge cases
- a very small number of out-of-region postcodes are included as stray exceptions rather than treated as impossible
- these postcode choices do not represent actual case activity, referral patterns, or operational footprints for Region Hovedstaden or Region Sjælland; they are synthetic visual scaffolding chosen to make the map readable

Supporting files:

- `postal_codes_denmark.geojson` contains real Danish postcode polygons used by the generated map figure
- `postcode_service_areas.csv` documents which postcode pools are treated as Hovedstaden, Sjælland, shared overlap, or out-of-region noise

The generated map therefore uses real postcode geometry, while still keeping the case records synthetic. The shapes are real; the postcode assignment pattern is not intended as a claim about the real regions.
