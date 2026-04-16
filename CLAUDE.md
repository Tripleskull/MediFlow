# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# After activating the project virtualenv:

# Cross-platform analysis refresh
python -m src.cli analyse --no-compile

# Refresh generated report snippets and try PDF compile if a TeX engine exists
python -m src.cli render-docs

# Compile curated report/slides from existing generated snippets
python -m src.cli compile-docs

# Create a self-contained Overleaf upload bundle
python -m src.cli export-overleaf

# Run all tests
python -m pytest -q

# Run a single test
python -m pytest tests/test_analyse.py::test_meditrack_case_level_deduplication_is_applied -q
```

The pipeline writes figures to `output/figures/`, JSON context to `output/report_context.json`, and generated snippet files to `output/generated/`. The editable LaTeX entrypoints are `report/mediflow_report.tex` and `report/mediflow_slides.tex`. The Overleaf export writes a self-contained bundle to `output/mediflow_overleaf/` plus `output/mediflow_overleaf.zip`.

## Architecture

The project is a single-pass analysis pipeline over two synthetic healthcare datasets.

**Data sources** (`data/`):

- `careflow_north.csv` - the "clean" source system; dates stored as `YYYYMMDD` integers
- `meditrack_east.csv` - the "messy" source system; loaded entirely as `dtype=str` because dates mix multiple formats
- `postal_codes_denmark.geojson` + `postcode_service_areas.csv` - real Danish postcode geometry and curated postcode pools for the geography figure

**`src/analyse.py`** is the pipeline entry point for parsing, cleaning, metrics, and figures:

- `build_analysis_results()` returns an `AnalysisResults` dataclass that acts as the shared results contract
- `parse_careflow()` / `parse_meditrack()` handle source-specific ingestion
- figure-drawing functions consume cleaned frames and write PNGs to `output/figures/`
- metrics are computed once and passed downstream rather than typed into prose

**`src/reporting.py`** handles generated reporting assets:

- `build_report_context()` serialises current metrics to `output/report_context.json`
- `build_generated_snippets()` creates LaTeX snippet content under `output/generated/`
- `compile_curated_documents()` compiles the editable `report/` entrypoints when a TeX engine is available

**`src/cli.py`** is the cross-platform command entrypoint:

- `analyse` refreshes the full pipeline
- `render-docs` refreshes generated reporting assets
- `compile-docs` compiles the curated LaTeX entrypoints from existing generated files
- `export-overleaf` creates an upload-ready Overleaf bundle with root-level `main.tex` / `slides.tex`, plus `generated/` and `figures/`

**`report/`** contains editable LaTeX masters:

- `mediflow_report.tex` chooses which generated tables, figures, and interpretation prompts appear in the article PDF
- `mediflow_slides.tex` chooses which generated frames appear in the slide deck PDF

**`tests/test_analyse.py`** contains regression tests that pin exact metric values and document-snippet behavior. When synthetic data changes, these tests should break until the new values are reviewed and intentionally updated.

## Key design decisions

- **MediTrack loaded as all-string** - this is intentional; coercion happens after profiling
- **`AnalysisResults` is the contract** - all figures and generated report assets should derive from that dataclass
- **Robust vs exploratory KPIs** - MediTrack treatment duration remains explicitly exploratory because of high inversion rates
- **Generated facts, curated PDFs** - values and tables are generated, but the final LaTeX structure is intentionally editable in `report/`
