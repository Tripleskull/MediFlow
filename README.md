# MediFlow

**Data Quality & KPI Harmonisation for Multi-System Healthcare Data**

MediFlow is a portfolio project demonstrating how to transform inconsistent, multi-source healthcare data into reliable, comparable KPIs through a reproducible Python pipeline.

## Problem

Healthcare organisations often collect patient data across multiple systems with different formats, quality levels, and conventions. Comparing KPIs across these systems requires careful cleaning, mapping, and validation before any meaningful analysis is possible.

## Approach

MediFlow ingests synthetic data from two fictional hospital systems:

- **System A** — well-structured, consistent formats, high completeness
- **System B** — realistic quality issues: mixed date formats, missing values, duplicates, logical errors

The pipeline cleans, standardises, and validates both datasets, then computes comparable KPIs (completion rates, wait times, treatment durations, cancellation rates) and produces a standalone data quality report.

## Project structure

```
src/              Pipeline modules (ingestion, cleaning, validation, KPI logic)
data/             Synthetic input datasets
outputs/          Generated reports and dashboards
tests/            Unit tests
docs/             Project documentation
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Status

Early development — synthetic data generation and pipeline scaffolding in progress.
