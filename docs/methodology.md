# Methodology

## Why the final analysis is code-first

The final MediFlow analysis lives in [src/analyse.py](../src/analyse.py) because a script is easier to review, rerun, diff, and test than a notebook-only workflow — and the project is about reproducible KPI and data-quality claims, not just charts.

## What the exploratory work taught us

Before the final pipeline was written, the approach was shaped by exploratory work on heterogeneous operational extracts. That exploratory phase surfaced a few repeated lessons:

- ingestion should not assume the first encoding guess is correct
- ambiguous date columns should be inspected as raw text before coercion
- mixed-format populations should be measured, not hand-waved away
- duplicate rows and duplicate case identifiers are different problems
- candidate KPI definitions need to be tested against the actual data before they are published

Those lessons are now part of the scripted analysis instead of being left in informal working notes.

## How MediFlow applies those lessons

### 1. Load raw values deliberately

The messy system is first treated as a text-heavy operational extract. This keeps the parser honest and makes it possible to describe what the raw data actually looked like before cleanup.

### 2. Parse mixed date formats explicitly

The analysis profiles date-format populations and then parses them with an explicit mixed-format strategy instead of relying on silent auto-inference alone.

### 3. Keep the Excel use case visible

Part of the original work was helping users turn exported date fields into usable Excel dates. That is why the project keeps a short Excel formula example in the report. The formulas are documentation of the exploration, while Python is the source of truth for the final outputs.

For the clean export pattern:

```excel
=IF(A2=0,"",DATE(LEFT(TEXT(A2,"00000000"),4),MID(TEXT(A2,"00000000"),5,2),RIGHT(TEXT(A2,"00000000"),2)))
```

For the mixed export pattern:

```excel
=IF(A2="","",IF(ISNUMBER(SEARCH("/",A2)),DATE(MID(A2,FIND("/",A2,FIND("/",A2)+1)+1,4),LEFT(A2,FIND("/",A2)-1),MID(A2,FIND("/",A2)+1,FIND("/",A2,FIND("/",A2)+1)-FIND("/",A2)-1)),DATE(RIGHT(LEFT(A2,10),4),MID(A2,4,2),LEFT(A2,2))))
```

### 4. Separate robust KPIs from exploratory diagnostics

Some metrics are strong enough for direct comparison, such as finished-case rates or cancellation rates. Others, especially treatment duration in the messy system, stay exploratory and are labelled as such in the outputs.

### 5. Collapse duplicate cases at the analytical grain

Exact-row deduplication is not enough when the case identifier itself can repeat. MediFlow therefore distinguishes between full-row duplicates and case-level duplicates and resolves both before reporting case counts.

### 6. Generate narrative summaries from computed metrics

The project avoids hand-typed scorecards and report claims where possible. The goal is for prose, tables, and figures to reflect the same computed results.

### 7. Keep the clean system plausible, not perfect

The clean synthetic source is intentionally cleaner than the messy source, but it is not modelled as flawless. It includes a visible unresolved backlog by registration month and an administrative timestamp that can predate the 2022 study window.

### 8. Preserve structural variation across categories

Cancellation behavior should not be flat across every pathway category. Both synthetic systems therefore include category-level cancellation gradients, so some groups are consistently lower-risk and others higher-risk.

Category volumes should not look flat either. Both systems therefore use deliberately uneven group sizes, with a few large pathway buckets, some medium ones, and some clearly smaller ones. The exact labels differ across systems, but the overall large/mid/small shape is intentionally comparable.

Treatment-time spread should not split neatly by source system alone. Both synthetic systems therefore use overlapping category-level spread ranges, so the category differences matter more than a simple clean-versus-messy divide.

### 9. Keep geography synthetic in cases, but real in shape

The project does not use invented postcode coordinates anymore. Instead, the case-level postcode fields are drawn from curated real postcode pools for Region Hovedstaden and Region Sjaelland, with a small amount of intentional overlap and a few out-of-region exceptions.

That does not mean the synthetic case geography corresponds to actual regional activity in Region Hovedstaden or Region Sjaelland. The postcode pools were chosen to produce a clear and readable map, not to recreate real service footprints or referral flows.

That design keeps the service areas readable and plausible:

- most CareFlow cases fall in Region Hovedstaden postcodes
- most MediTrack cases fall in Region Sjaelland postcodes
- some shared postcodes remain to mimic cross-boundary leakage and operational errors
- the map itself is rendered from real Danish postcode polygons rather than synthetic centroids

## Relationship to the repository

- [src/analyse.py](../src/analyse.py) contains the reproducible analysis pipeline.
- [data/dataset_notes.md](../data/dataset_notes.md) documents the intended source semantics.
- [data/postcode_service_areas.csv](../data/postcode_service_areas.csv) records the explicit postcode pools behind the geographic story.
- [tests/test_analyse.py](../tests/test_analyse.py) protects KPI-critical parsing and deduplication behavior.

This keeps the exploratory reasoning visible while making the final project feel like an engineered analysis rather than a one-off notebook run.
