"""Smoke tests for figure rendering, generated snippets, and the report context.

These tests catch silent breakage: a figure function that errors and
produces no PNG, a snippet whose render call returns empty text, or a
report-context key that disappears. They are not pixel-comparison tests —
they only assert presence and a small non-empty bound.
"""

from __future__ import annotations

import json

import pytest

from src.analyse import build_analysis_results
from src.figures import ACTIVE_FIGURE_FILENAMES, generate_figures
from src.reporting import (
    CONTEXT_JSON_PATH,
    FIGURE_SPECS,
    build_generated_snippets,
    build_report_context,
)


@pytest.fixture(scope="module")
def analysis_results():
    return build_analysis_results()


@pytest.fixture(scope="module")
def report_context(analysis_results):
    return build_report_context(analysis_results)


def test_every_active_figure_is_rendered(analysis_results, tmp_path, monkeypatch):
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    monkeypatch.setattr("src.figures.FIG_DIR", figures_dir)
    generate_figures(analysis_results)

    for filename in ACTIVE_FIGURE_FILENAMES:
        path = figures_dir / filename
        assert path.exists(), f"missing figure: {filename}"
        assert path.stat().st_size > 1024, f"suspiciously small figure: {filename}"


def test_generated_snippets_cover_every_figure_and_static_block(report_context):
    snippets = build_generated_snippets(report_context)

    static_snippets = {
        "00_document_macros.tex",
        "11_foundation_points.tex",
        "12_current_run_highlights.tex",
        "13_excel_date_parsing.tex",
        "20_kpi_table.tex",
        "21_scorecard_table.tex",
        "30_careflow_category_table.tex",
        "31_meditrack_category_table.tex",
        "32_careflow_region_table.tex",
        "33_meditrack_region_table.tex",
        "40_exec_interpretation.tex",
        "41_quality_interpretation.tex",
        "42_geo_interpretation.tex",
        "70_slide_source_truth.tex",
        "71_slide_kpi_snapshot.tex",
        "72_slide_excel_date_parsing.tex",
        "99_slide_generated_interpretation.tex",
    }

    missing_static = static_snippets - set(snippets)
    assert not missing_static, f"missing static snippets: {missing_static}"

    for spec in FIGURE_SPECS:
        stem = spec["filename"].rsplit(".", 1)[0]
        figure_snippet = next((name for name in snippets if name.endswith(f"_figure_{stem}.tex")), None)
        slide_snippet = next((name for name in snippets if name.endswith(f"_slide_{stem}.tex")), None)
        assert figure_snippet is not None, f"missing figure snippet for {stem}"
        assert slide_snippet is not None, f"missing slide snippet for {stem}"

    for name, content in snippets.items():
        assert content.strip(), f"empty snippet: {name}"


def test_report_context_has_load_bearing_keys(report_context):
    expected_keys = {
        "build_timestamp",
        "build_date",
        "analysis_run_label",
        "careflow_raw_rows",
        "meditrack_raw_rows",
        "source_truth_files",
        "foundation_points",
        "current_run_highlights",
        "careflow_metrics",
        "meditrack_metrics",
        "scorecard_rows",
        "careflow_category_rows",
        "meditrack_category_rows",
        "careflow_region_rows",
        "meditrack_region_rows",
        "registered_at_format",
        "meditrack_duplicate_profile",
        "figure_specs",
        "auto_exec_summary",
        "auto_quality_summary",
        "auto_geo_summary",
    }
    missing = expected_keys - set(report_context)
    assert not missing, f"missing report context keys: {missing}"


def test_report_context_json_round_trips(report_context):
    payload = json.dumps(report_context, ensure_ascii=False, default=str)
    parsed = json.loads(payload)
    assert parsed["build_date"] == report_context["build_date"]
    assert isinstance(parsed["figure_specs"], list) and parsed["figure_specs"]


def test_report_context_json_file_parses_when_present():
    if not CONTEXT_JSON_PATH.exists():
        pytest.skip("report_context.json has not been written yet")
    data = json.loads(CONTEXT_JSON_PATH.read_text(encoding="utf-8"))
    assert "careflow_metrics" in data
    assert "figure_specs" in data
