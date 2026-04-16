from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.analyse import (
    build_analysis_results,
    build_automation_profile,
    build_foundation_markdown,
    care_group_display_label,
    collapse_meditrack_status_for_comparison,
)
from src.reporting import (
    MASTER_REPORT_PATH,
    MASTER_SLIDES_PATH,
    build_generated_snippets,
    build_report_context,
    render_overleaf_macros,
    render_overleaf_master,
)


@pytest.fixture(scope="module")
def analysis_results():
    return build_analysis_results()


def test_core_metrics_match_current_synthetic_dataset(analysis_results):
    careflow_metrics = analysis_results.careflow_metrics
    meditrack_metrics = analysis_results.meditrack_metrics

    assert careflow_metrics["registered_cases"] == 26179
    assert meditrack_metrics["registered_cases"] == 17165
    assert careflow_metrics["completed_cases"] == 20456
    assert meditrack_metrics["completed_cases"] == 6123
    assert careflow_metrics["completed_pct"] == pytest.approx(78.13896634707208)
    assert meditrack_metrics["completed_pct"] == pytest.approx(35.67142441013691)
    assert careflow_metrics["open_cases"] == 3700
    assert careflow_metrics["open_pct"] == pytest.approx(14.133465754994461)
    assert careflow_metrics["cancelled_cases"] == 2023
    assert careflow_metrics["cancelled_pct"] == pytest.approx(7.727567897933458)
    assert careflow_metrics["median_duration_days"] == pytest.approx(48.0)
    assert meditrack_metrics["median_duration_days"] == pytest.approx(57.0)
    assert careflow_metrics["inversion_pct"] == pytest.approx(0.15643332029722332)
    assert meditrack_metrics["inversion_pct"] == pytest.approx(45.99052751918994)


def test_meditrack_case_level_deduplication_is_applied(analysis_results):
    duplicate_profile = analysis_results.meditrack_duplicate_profile

    assert duplicate_profile["raw_rows"] == 17262
    assert duplicate_profile["exact_duplicate_rows"] == 81
    assert duplicate_profile["rows_after_exact_dedup"] == 17181
    assert duplicate_profile["duplicate_case_groups"] == 16
    assert duplicate_profile["duplicate_case_rows"] == 32
    assert duplicate_profile["case_rows_removed"] == 16
    assert analysis_results.meditrack["RefNo"].is_unique


def test_scorecard_rows_are_computed_not_hand_typed(analysis_results):
    rows = {row["dimension"]: row for row in analysis_results.scorecard_rows}

    assert rows["Parse rate"]["careflow_text"] == "OK: 100.0%"
    assert rows["Parse rate"]["meditrack_text"] == "OK: 100.0%"
    assert "median 48 d" in rows["Treatment-time KPI"]["careflow_text"]
    assert "median 57 d" in rows["Treatment-time KPI"]["meditrack_text"]
    assert "81 exact rows and 16 extra case rows" in rows["Duplicates"]["meditrack_text"]
    assert "50.1% slash" in rows["Date format"]["meditrack_text"]
    assert rows["Temporal coverage"]["careflow_text"] == "Caution: 11/12 months"
    assert rows["Temporal coverage"]["meditrack_text"] == "OK: 12/12 months"


def test_foundation_markdown_makes_exploration_visible(analysis_results):
    markdown = build_foundation_markdown(analysis_results)

    assert "candidate file encodings" in markdown
    assert "mixed-format date populations" in markdown
    assert "CareFlow finished case rate (Completed): 78.1%" in markdown
    assert "CareFlow open rate at year end: 14.1%" in markdown
    assert "50.1% slash, 49.9% dash" in markdown
    assert "81 exact rows removed and 16 extra case rows collapsed" in markdown
    assert "admin dates can start before 2022" in markdown
    assert "Excel date parsing note" in markdown
    assert '=IF(A2=0,"",DATE(LEFT(TEXT(A2,"00000000"),4)' in markdown


def test_careflow_admin_history_is_visible_in_clean_dataset(analysis_results):
    careflow = analysis_results.careflow

    assert "DT_CREATED" in careflow.columns
    assert careflow["DT_CREATED"].min().year == 2016
    assert careflow["DT_REG"].min().year == 2022
    assert (careflow["status"] == "Open").any()


def test_monthly_cancellation_rates_are_not_uniform(analysis_results):
    careflow_monthly = analysis_results.careflow.groupby(["reg_month", "status"]).size().unstack(fill_value=0)
    meditrack_monthly = analysis_results.meditrack.groupby(["reg_month", "status"]).size().unstack(fill_value=0)

    careflow_cancel_pct = careflow_monthly["Cancelled"] / careflow_monthly.sum(axis=1) * 100
    meditrack_cancel_pct = meditrack_monthly["Cancelled"] / meditrack_monthly.sum(axis=1) * 100

    assert careflow_cancel_pct.max() - careflow_cancel_pct.min() >= 7.5
    assert meditrack_cancel_pct.max() - meditrack_cancel_pct.min() >= 6.5


def test_category_cancellation_rates_are_distinct_in_both_datasets(analysis_results):
    careflow_grouped = analysis_results.careflow.groupby("TRACK").agg(
        total=("CARE_REF", "size"),
        cancelled=("status", lambda s: (s == "Cancelled").sum()),
    )
    careflow_cancel_pct = careflow_grouped["cancelled"] / careflow_grouped["total"] * 100

    meditrack_grouped = analysis_results.meditrack.groupby("CareGroup").agg(
        total=("RefNo", "size"),
        cancelled=("status", lambda s: (s == "Cancelled").sum()),
    )
    meditrack_cancel_pct = meditrack_grouped["cancelled"] / meditrack_grouped["total"] * 100

    assert careflow_cancel_pct.max() - careflow_cancel_pct.min() >= 9.0
    assert meditrack_cancel_pct.max() - meditrack_cancel_pct.min() >= 9.0
    assert careflow_cancel_pct.max() > 12.0
    assert meditrack_cancel_pct.max() > 12.0
    assert careflow_cancel_pct.min() < 4.0
    assert meditrack_cancel_pct.min() < 3.5


def test_category_volumes_are_not_near_uniform_in_either_dataset(analysis_results):
    careflow_counts = analysis_results.careflow["TRACK"].value_counts()
    meditrack_counts = analysis_results.meditrack["CareGroup"].value_counts()

    careflow_share = careflow_counts / careflow_counts.sum()
    meditrack_share = meditrack_counts / meditrack_counts.sum()

    assert careflow_counts.max() / careflow_counts.min() > 2.5
    assert meditrack_counts.max() / meditrack_counts.min() > 3.0
    assert careflow_share.max() > 0.22
    assert meditrack_share.max() > 0.27
    assert careflow_share.min() < 0.09
    assert meditrack_share.min() < 0.09
    assert careflow_share.sort_values(ascending=False).head(2).sum() > 0.42
    assert meditrack_share.sort_values(ascending=False).head(2).sum() > 0.49


def test_category_duration_spread_varies_within_datasets_and_overlaps_across_them(analysis_results):
    careflow_done = analysis_results.careflow.loc[
        (analysis_results.careflow["status"] == "Completed")
        & analysis_results.careflow["duration_days_raw"].notna()
        & (analysis_results.careflow["duration_days_raw"] >= 0)
    ]
    meditrack_done = analysis_results.meditrack.loc[
        (analysis_results.meditrack["status"] == "Done")
        & analysis_results.meditrack["duration_days_raw"].notna()
        & (analysis_results.meditrack["duration_days_raw"] >= 0)
    ]

    careflow_std = careflow_done.groupby("TRACK")["duration_days_raw"].std()
    meditrack_std = meditrack_done.groupby("CareGroup")["duration_days_raw"].std()

    assert careflow_std.max() - careflow_std.min() > 30.0
    assert meditrack_std.max() - meditrack_std.min() > 30.0
    assert abs(careflow_std.mean() - meditrack_std.mean()) < 6.0
    assert careflow_std.min() < meditrack_std.min() < careflow_std.max()
    assert meditrack_std.min() < careflow_std.mean() < meditrack_std.max()


def test_automation_profiles_use_relative_finished_case_share(analysis_results):
    careflow_profile = build_automation_profile(analysis_results.careflow, "TRACK", "CARE_REF", "Completed")
    meditrack_profile = build_automation_profile(
        analysis_results.meditrack,
        "CareGroup",
        "RefNo",
        "Done",
        label_transform=care_group_display_label,
    )

    assert careflow_profile["share_pct"].sum() == pytest.approx(100.0)
    assert meditrack_profile["share_pct"].sum() == pytest.approx(100.0)
    assert careflow_profile["share_pct"].max() > 20.0
    assert meditrack_profile["share_pct"].max() > 15.0


def test_postcode_geography_uses_explicit_regional_pools(analysis_results):
    reference = pd.read_csv(
        Path("data") / "postcode_service_areas.csv",
        dtype={"postcode": "string"},
    ).set_index("postcode")

    careflow_postcodes = analysis_results.careflow_raw["ZIP_PAT"].astype("string")
    meditrack_postcodes = analysis_results.meditrack_raw["PostalArea"].astype("string")
    careflow_regions = careflow_postcodes.map(reference["actual_region"])
    meditrack_regions = meditrack_postcodes.map(reference["actual_region"])

    assert careflow_regions.notna().all()
    assert meditrack_regions.notna().all()

    careflow_region_share = careflow_regions.value_counts(normalize=True) * 100
    meditrack_region_share = meditrack_regions.value_counts(normalize=True) * 100
    shared_postcodes = set(careflow_postcodes.unique()) & set(meditrack_postcodes.unique())
    other_postcodes = set(reference.index[reference["actual_region"] == "Other"])

    assert careflow_region_share["Hovedstaden"] > 90.0
    assert 3.0 < careflow_region_share["Sjaelland"] < 7.0
    assert careflow_region_share["Other"] < 2.0
    assert meditrack_region_share["Sjaelland"] > 90.0
    assert 2.0 < meditrack_region_share["Hovedstaden"] < 6.0
    assert meditrack_region_share["Other"] < 2.5
    assert {"2670", "4000", "4600"}.issubset(shared_postcodes)
    assert shared_postcodes.isdisjoint(other_postcodes)
    assert len(set(careflow_postcodes.unique()) & other_postcodes) >= 3
    assert len(set(meditrack_postcodes.unique()) & other_postcodes) >= 3


def test_meditrack_comparison_view_collapses_open_workflow_states(analysis_results):
    comparison = collapse_meditrack_status_for_comparison(analysis_results.meditrack)
    counts = comparison["comparison_status"].value_counts()

    assert set(counts.index) == {"Done", "Open", "Cancelled"}
    assert counts["Done"] == 6123
    assert counts["Cancelled"] == 1299
    assert counts["Open"] == 9743


def test_generated_report_snippets_use_current_analysis_context(analysis_results):
    context = build_report_context(analysis_results)
    snippets = build_generated_snippets(context)

    assert "src/reporting.py" in context["source_truth_files"]
    assert "analysis_run_label" in context
    assert snippets["12_current_run_highlights.tex"].startswith("% AUTO-GENERATED")
    assert r"\MediFlowCurrentRunHighlights" in snippets["12_current_run_highlights.tex"]
    assert "20,456" not in snippets["20_kpi_table.tex"]
    assert "6,123" not in snippets["20_kpi_table.tex"]
    assert r"\MediFlowKpiRows" in snippets["20_kpi_table.tex"]
    assert r"\MediFlowScorecardRows" in snippets["21_scorecard_table.tex"]
    assert r"\MediFlowMediTrackCategoryRows" in snippets["31_meditrack_category_table.tex"]
    assert "report_context.json" in snippets["00_document_macros.tex"]
    assert r"\newcommand{\MediFlowAnalysisRunLabel}" in snippets["00_document_macros.tex"]
    assert "rough check" in snippets["00_document_macros.tex"]
    assert "status and volume comparisons" in snippets["00_document_macros.tex"]
    assert "real regional activity" in snippets["00_document_macros.tex"]
    assert "The map is there to help the eye" not in snippets["00_document_macros.tex"]
    assert 'LEFT(TEXT(A2,"00000000"),4)' in snippets["13_excel_date_parsing.tex"]
    assert "not the source of truth" in snippets["13_excel_date_parsing.tex"]
    assert r"\begin{tabularx}" in snippets["13_excel_date_parsing.tex"]


def test_curated_master_docs_reference_generated_snippets(analysis_results):
    context = build_report_context(analysis_results)
    snippets = build_generated_snippets(context)
    report_master = MASTER_REPORT_PATH.read_text(encoding="utf-8")
    slides_master = MASTER_SLIDES_PATH.read_text(encoding="utf-8")

    assert "00_document_macros.tex" in report_master
    assert "13_excel_date_parsing.tex" in report_master
    assert "monthly_volume_2022.png" in report_master
    assert "geo_top15_postalcodes.png" in report_master
    assert "automation_matrix_meditrack.png" in report_master
    assert "automation_matrix_combined.png" in report_master
    assert "Field mapping: what can compare?" in slides_master
    assert "Date cleaning: CareFlow Excel formula" in slides_master
    assert "Date cleaning: MediTrack Excel formula" in slides_master
    assert "Automation pattern: MediTrack --- volume and variation" in slides_master
    assert "Appendix: synthetic postcode geography" in slides_master
    assert "monthly_status_careflow.png" in snippets["81_slide_monthly_status_careflow.tex"]
    assert "geo_top15_postalcodes.png" in snippets["87_slide_geo_top15_postalcodes.tex"]
    assert "automation_matrix_combined.png" in snippets["90_slide_automation_matrix_combined.tex"]
    assert r"\MediFlowAutoTag" in report_master
    assert r"\MediFlowAnalysisRunLabel" in report_master
    assert context["master_report_path"] == "report/mediflow_report.tex"
    assert "Source files" not in report_master
    assert r"\texttt{\MediFlowContextPath}" not in report_master


def test_overleaf_export_rewrites_paths_for_root_level_compile(analysis_results):
    context = build_report_context(analysis_results)
    snippets = build_generated_snippets(context)
    overleaf_report = render_overleaf_master(MASTER_REPORT_PATH)
    overleaf_slides = render_overleaf_master(MASTER_SLIDES_PATH)
    overleaf_macros = render_overleaf_macros(snippets["00_document_macros.tex"])

    assert r"\graphicspath{{figures/}}" in overleaf_report
    assert r"\input{generated/00_document_macros.tex}" in overleaf_report
    assert "../output/generated/" not in overleaf_report
    assert r"\graphicspath{{figures/}}" in overleaf_slides
    assert r"\input{generated/00_document_macros.tex}" in overleaf_slides
    assert "../output/generated/" not in overleaf_slides
    assert "../output/figures/" not in overleaf_slides
    assert r"\newcommand{\MediFlowContextPath}{\detokenize{report_context.json}}" in overleaf_macros
    assert r"\newcommand{\MediFlowGeneratedDir}{\detokenize{generated}}" in overleaf_macros
