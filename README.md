# MediFlow

**An automated analysis pipeline for comparing two synthetic healthcare case systems**

MediFlow is a portfolio project built from the structure of a real analysis case. It uses synthetic data sources modeled on the original systems and turns the workflow into a repeatable pipeline: ingesting and cleaning messy operational extracts, comparing KPI quality across systems, and generating a report and slide deck from the same run.

The data in this repository is synthetic, but the analytical problems are realistic: mixed date formats, duplicate case IDs, uneven month coverage, and fields that look comparable but need careful handling.

## Start Here

If you are opening the repo on GitHub, these are the best entry points:

1. [`report/mediflow_report.tex`](report/mediflow_report.tex) for the full written story
2. [`report/mediflow_slides.tex`](report/mediflow_slides.tex) for the presentation deck
3. [`docs/methodology.md`](docs/methodology.md) for the analytical foundation
4. [`src/analyse.py`](src/analyse.py) for the source-of-truth pipeline
5. [`output/mediflow_overleaf`](output/mediflow_overleaf) for the current Overleaf-ready export

## What The Project Does

The project compares two synthetic systems:

- `CareFlow North`: cleaner, easier to parse, but missing December registrations
- `MediTrack East`: richer category detail, but mixed date formats, duplicates, and weaker treatment-time logic

The pipeline answers four practical questions:

- What can be compared safely across the two systems?
- Which KPI values are robust enough to headline?
- Which values should stay exploratory?
- How do we turn the same checks into a repeatable report and slide deck?

## Repo Layout

```text
src/      Source-of-truth analysis and reporting code
report/   Curated LaTeX files for the report and slides
docs/     Method notes and project-facing documentation
data/     Synthetic datasets and field notes
tests/    Regression checks for parsing, deduplication, and KPI logic
output/   Generated figures, report context, and Overleaf export
```

The repo is meant to read from top to bottom in that order: story, method, code, generated outputs.

## Running The Analysis

Create and activate a virtual environment:

```bash
python -m venv .venv
```

- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- macOS / Linux: `source .venv/bin/activate`

Install dependencies and run:

```bash
python -m pip install -r requirements.txt
python -m src.cli analyse --no-compile
python -m pytest -q
```

## Report And Slide Workflow

The report and slides are deliberately split into two parts:

- editable structure in [`report/mediflow_report.tex`](report/mediflow_report.tex) and [`report/mediflow_slides.tex`](report/mediflow_slides.tex)
- generated facts in [`output/report_context.json`](output/report_context.json) and [`output/generated`](output/generated)

Useful commands:

- Refresh figures and generated LaTeX snippets: `python -m src.cli analyse --no-compile`
- Try local PDF compile if a TeX engine is installed: `python -m src.cli compile-docs`
- Build the self-contained Overleaf export: `python -m src.cli export-overleaf`

## Overleaf

Upload the contents of [`output/mediflow_overleaf`](output/mediflow_overleaf) to Overleaf, or upload [`output/mediflow_overleaf.zip`](output/mediflow_overleaf.zip).

That export contains:

- `main.tex`
- `slides.tex`
- `generated/`
- `figures/`
- `report_context.json`

So Overleaf does not need the full local repo layout.

## Notes

- The postcode map uses real Danish postcode geometry, but the postcode assignments are synthetic and were chosen for readable visuals only.
- The pipeline keeps robust results and exploratory results separate on purpose.
- The report and slide deck are curated by hand, but the numbers and tables come from the same analysis run.
