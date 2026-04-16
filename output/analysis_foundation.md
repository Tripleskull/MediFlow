# How this analysis was built

This project started with exploratory work on messy operational extracts. The script now turns the repeatable parts of that work into one workflow, so the report and slides can be refreshed from the same source.

## Checks we did before locking the pipeline

- candidate file encodings and import assumptions
- raw date strings before coercion into datetimes
- mixed-format date populations in the messy source system
- duplicate rows versus duplicate case identifiers
- competing treatment-time definitions and whether they were robust enough for KPI use

## What the current pipeline does every run

- the messy source is loaded as text first, then parsed with explicit mixed-format rules
- duplicate case identifiers are collapsed at the `RefNo` case grain after exact deduplication
- robust and exploratory metrics are kept separate in the figures and scorecards
- postcode geography uses real Danish postcode polygons, while postcode choices stay synthetic and are only there for readable visuals
- summary prose is generated from computed metrics instead of being typed into the report by hand

## Excel date parsing note

One practical request in the original work was helping a department turn exported date values into usable Excel dates. The same issue is reflected here: one source looks like `YYYYMMDD`, while the other mixes slash and dash timestamp styles.

For the clean export pattern, the Excel formula was:

```excel
=IF(A2=0,"",DATE(LEFT(TEXT(A2,"00000000"),4),MID(TEXT(A2,"00000000"),5,2),RIGHT(TEXT(A2,"00000000"),2)))
```

For the mixed-format export pattern, the Excel formula was:

```excel
=IF(A2="","",IF(ISNUMBER(SEARCH("/",A2)),DATE(MID(A2,FIND("/",A2,FIND("/",A2)+1)+1,4),LEFT(A2,FIND("/",A2)-1),MID(A2,FIND("/",A2)+1,FIND("/",A2,FIND("/",A2)+1)-FIND("/",A2)-1)),DATE(RIGHT(LEFT(A2,10),4),MID(A2,4,2),LEFT(A2,2))))
```

The Python pipeline now mirrors that logic. Excel is included here as a worked example from the exploration, not as the source of truth for the final report.

## Current run highlights

- CareFlow finished case rate (Completed): 78.1%
- CareFlow open rate at year end: 14.1%
- CareFlow median treatment time: 48 days
- MediTrack finished case rate (Done): 35.7%
- MediTrack finish-before-registration rate: 46.0%
- MediTrack RegisteredAt date styles: 50.1% slash, 49.9% dash
- MediTrack duplicate cleanup in the pipeline: 81 exact rows removed and 16 extra case rows collapsed

## Plain-language read

CareFlow is the cleaner system for direct KPI comparison. It still has open cases at year end, and its admin dates can start before 2022, so the data is not unrealistically neat. MediTrack is useful for status and volume comparison, but its treatment-time measure is still only a rough check because finish dates often come before registration dates. The postcode map uses real postcode shapes, but the postcode choices are synthetic and were picked for visual separation rather than to reflect actual Region Hovedstaden or Region Sjaelland activity.
