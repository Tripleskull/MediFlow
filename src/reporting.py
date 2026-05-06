"""Generated snippet rendering and editable LaTeX document support for MediFlow."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

import pandas as pd

from .analyse import OUTPUT_DIR, POSTCODE_REFERENCE_PATH, build_foundation_markdown, log
from .formats import format_days, format_int, format_pct
from .labels import display_group_label

if TYPE_CHECKING:
    from .analyse import AnalysisResults


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "report"
MASTER_REPORT_PATH = REPORT_DIR / "mediflow_report.tex"
MASTER_SLIDES_PATH = REPORT_DIR / "mediflow_slides.tex"
GENERATED_DIR = OUTPUT_DIR / "generated"
CONTEXT_JSON_PATH = OUTPUT_DIR / "report_context.json"
LEGACY_REPORT_TEX_PATH = OUTPUT_DIR / "mediflow_report.tex"
LEGACY_SLIDES_TEX_PATH = OUTPUT_DIR / "mediflow_slides.tex"
LEGACY_OVERLEAF_DIR = OUTPUT_DIR / "overleaf"
OVERLEAF_DIR = OUTPUT_DIR / "mediflow_overleaf"
OVERLEAF_MAIN_PATH = OVERLEAF_DIR / "main.tex"
OVERLEAF_SLIDES_PATH = OVERLEAF_DIR / "slides.tex"
OVERLEAF_GENERATED_DIR = OVERLEAF_DIR / "generated"
OVERLEAF_FIGURES_DIR = OVERLEAF_DIR / "figures"
OVERLEAF_ARCHIVE_BASE = OUTPUT_DIR / "mediflow_overleaf"
LATEX_AUXILIARY_EXTENSIONS = [".aux", ".log", ".out", ".toc", ".nav", ".snm", ".fls", ".fdb_latexmk"]
WINDOWS_TEX_BIN_DIRS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
    Path("C:/Program Files/MiKTeX/miktex/bin/x64"),
]

AUTO_TAG = "[AUTO-GENERATED INTERPRETATION]"
GENERATED_REFRESH_NOTE = "Refresh with python -m src.cli analyse --no-compile."

FIGURE_SPECS = [
    {
        "filename": "monthly_volume_2022.png",
        "title": "Monthly registration volume",
        "caption": "Cases registered each month in the 2022 study window.",
    },
    {
        "filename": "monthly_status_careflow.png",
        "title": "CareFlow status by registration month",
        "caption": "Completed, open, and cancelled CareFlow cases by registration month.",
    },
    {
        "filename": "monthly_status_meditrack.png",
        "title": "MediTrack status by registration month",
        "caption": "MediTrack workflow states are grouped into a comparison-ready Done / Open / Cancelled view.",
    },
    {
        "filename": "treatment_duration_boxplot.png",
        "title": "Treatment-time distribution",
        "caption": "Case duration after cleaning and status setup.",
    },
    {
        "filename": "kpi_comparison.png",
        "title": "KPI comparison",
        "caption": "Side-by-side KPI view. MediTrack treatment time stays marked as exploratory.",
    },
    {
        "filename": "missing_date_fields.png",
        "title": "Date-field completeness",
        "caption": "How complete the key date fields are in each dataset.",
    },
    {
        "filename": "date_span_outliers.png",
        "title": "Date-span outliers",
        "caption": "Date ranges by field, including earlier admin history and out-of-window dates.",
    },
    {
        "filename": "geo_top15_postalcodes.png",
        "title": "Synthetic geography on Danish postcode map",
        "caption": "Real Danish postcode shapes with synthetic postcode choices made for visual separation only.",
    },
    {
        "filename": "automation_matrix_careflow.png",
        "title": "CareFlow category pattern",
        "caption": "CareFlow category share, treatment-time spread, and cancellation rate for plotted finished cases.",
    },
    {
        "filename": "automation_matrix_meditrack.png",
        "title": "MediTrack category pattern",
        "caption": "MediTrack category share, treatment-time spread, and cancellation rate for plotted finished cases.",
    },
    {
        "filename": "automation_matrix_combined.png",
        "title": "Combined category pattern",
        "caption": "CareFlow and MediTrack categories in one view. Y-axis shows share within each dataset's plotted finished-case pool, and bubble size shows cancellation rate.",
    },
    {
        "filename": "data_quality_scorecard.png",
        "title": "Data-quality scorecard",
        "caption": "These scorecard values come straight from the current run.",
    },
]


def latex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def make_snippet_path(filename: str) -> Path:
    return GENERATED_DIR / filename


def snippet_stem_for_figure(filename: str) -> str:
    return Path(filename).stem


def with_generated_notice(content: str, label: str, needs_review: bool = False) -> str:
    lines = [
        f"% AUTO-GENERATED: {label}",
        f"% {GENERATED_REFRESH_NOTE}",
    ]
    if needs_review:
        lines.append("% Review this wording if the data changes.")
    lines.append(content)
    return "\n".join(lines)


def build_region_share_table(series: pd.Series) -> list[dict[str, object]]:
    reference = pd.read_csv(POSTCODE_REFERENCE_PATH, dtype={"postcode": "string"}).set_index("postcode")
    normalised = series.astype("string").str.strip().str.zfill(4)
    region_share = normalised.map(reference["actual_region"]).value_counts(normalize=True).mul(100.0)
    return [{"region": region, "share_pct": float(region_share.get(region, 0.0))} for region in ["Hovedstaden", "Sjaelland", "Other"]]


def build_category_summary(
    df: pd.DataFrame,
    group_col: str,
    id_col: str,
    completed_status: str,
) -> list[dict[str, object]]:
    grouped = (
        df.groupby(group_col)
        .agg(
            cases=(id_col, "size"),
            completed=("status", lambda s: (s == completed_status).sum()),
            cancelled=("status", lambda s: (s == "Cancelled").sum()),
        )
        .sort_values("cases", ascending=False)
        .reset_index()
    )
    grouped["share_pct"] = grouped["cases"] / grouped["cases"].sum() * 100.0
    grouped["completed_pct"] = grouped["completed"] / grouped["cases"] * 100.0
    grouped["cancel_pct"] = grouped["cancelled"] / grouped["cases"] * 100.0
    return grouped.to_dict(orient="records")


def build_current_run_highlights(results: AnalysisResults) -> list[str]:
    careflow_metrics = results.careflow_metrics
    meditrack_metrics = results.meditrack_metrics
    registered_profile = results.meditrack_format_profile.loc["RegisteredAt"]
    duplicate_profile = results.meditrack_duplicate_profile
    return [
        f"CareFlow finished case rate (Completed): {format_pct(careflow_metrics['completed_pct'])}",
        f"CareFlow open rate at year end: {format_pct(careflow_metrics['open_pct'])}",
        f"CareFlow median treatment time: {format_days(careflow_metrics['median_duration_days'])}",
        f"MediTrack finished case rate (Done): {format_pct(meditrack_metrics['completed_pct'])}",
        f"MediTrack finish-before-registration rate: {format_pct(meditrack_metrics['inversion_pct'])}",
        (
            "MediTrack RegisteredAt date styles: "
            f"{format_pct(registered_profile['slash_pct'])} slash / {format_pct(registered_profile['dash_pct'])} dash"
        ),
        (
            "MediTrack duplicate cleanup in the pipeline: "
            f"{duplicate_profile['exact_duplicate_rows']} exact rows removed and "
            f"{duplicate_profile['case_rows_removed']} extra case rows collapsed"
        ),
    ]


def build_auto_exec_summary(results: AnalysisResults) -> str:
    careflow_metrics = results.careflow_metrics
    meditrack_metrics = results.meditrack_metrics
    return (
        f"CareFlow supports a more direct KPI read in this run: {format_pct(careflow_metrics['completed_pct'])} finished, "
        f"{format_pct(careflow_metrics['open_pct'])} still open, and almost no finish-before-registration cases "
        f"({format_pct(careflow_metrics['inversion_pct'], decimals=3)}). "
        f"MediTrack is still useful for case counts and status mix, but {format_pct(meditrack_metrics['inversion_pct'])} of finished cases "
        f"fall before registration, so the {format_days(meditrack_metrics['median_duration_days'])} treatment-time figure should stay a rough check."
    )


def build_auto_quality_summary(results: AnalysisResults) -> str:
    duplicate_profile = results.meditrack_duplicate_profile
    registered_profile = results.meditrack_format_profile.loc["RegisteredAt"]
    return (
        "The two datasets needed different cleanup steps before comparison. "
        "CareFlow uses one date style and does not need case-level deduplication. "
        f"MediTrack needed two extra checks: parsing mixed RegisteredAt date styles ({format_pct(registered_profile['slash_pct'])} slash / "
        f"{format_pct(registered_profile['dash_pct'])} dash) and collapsing {duplicate_profile['exact_duplicate_rows']} exact duplicate rows plus "
        f"{duplicate_profile['case_rows_removed']} extra RefNo rows to case level. "
        "That makes the status and volume comparisons stronger than the treatment-time comparison."
    )


def build_auto_geo_summary(context: dict[str, object]) -> str:
    careflow_region_rows = context["careflow_region_rows"]
    meditrack_region_rows = context["meditrack_region_rows"]
    careflow_h = next(row["share_pct"] for row in careflow_region_rows if row["region"] == "Hovedstaden")
    careflow_s = next(row["share_pct"] for row in careflow_region_rows if row["region"] == "Sjaelland")
    meditrack_s = next(row["share_pct"] for row in meditrack_region_rows if row["region"] == "Sjaelland")
    meditrack_h = next(row["share_pct"] for row in meditrack_region_rows if row["region"] == "Hovedstaden")
    return (
        f"CareFlow mostly uses Hovedstaden postcodes ({format_pct(careflow_h)}) with a smaller Sjaelland share ({format_pct(careflow_s)}). "
        f"MediTrack mostly uses Sjaelland postcodes ({format_pct(meditrack_s)}) with some Hovedstaden spillover ({format_pct(meditrack_h)}). "
        "The postcode pools are synthetic and were chosen for readable visual separation, not to describe real regional activity."
    )


def define_value_macro(name: str, value: object) -> str:
    return f"\\newcommand{{\\{name}}}{{{latex_escape(value)}}}"


def define_block_macro(name: str, body: str) -> str:
    return "\n".join(
        [
            f"\\newcommand{{\\{name}}}{{%",
            body.rstrip(),
            "}",
        ]
    )


def render_kpi_rows_block(context: dict[str, object]) -> str:
    careflow_metrics = context["careflow_metrics"]
    meditrack_metrics = context["meditrack_metrics"]
    rows = [
        ("Registered cases (2022)", format_int(careflow_metrics["registered_cases"]), format_int(meditrack_metrics["registered_cases"]), "Case-level comparison"),
        ("Finished cases", format_int(careflow_metrics["completed_cases"]), format_int(meditrack_metrics["completed_cases"]), "Completed vs Done"),
        ("Finished case rate", format_pct(careflow_metrics["completed_pct"]), format_pct(meditrack_metrics["completed_pct"]), "Same concept"),
        ("Open rate", format_pct(careflow_metrics["open_pct"]), format_pct(meditrack_metrics["open_pct"]), "MediTrack groups Open, Pending, and In Progress"),
        ("Cancelled rate", format_pct(careflow_metrics["cancelled_pct"]), format_pct(meditrack_metrics["cancelled_pct"]), "Comparable"),
        ("Median treatment time", format_days(careflow_metrics["median_duration_days"]), format_days(meditrack_metrics["median_duration_days"]), "MediTrack exploratory"),
        ("Finish before registration", format_pct(careflow_metrics["inversion_pct"], decimals=3), format_pct(meditrack_metrics["inversion_pct"]), "Date-order check"),
    ]
    return "\n".join(
        f"{latex_escape(label)} & {latex_escape(careflow_value)} & {latex_escape(meditrack_value)} & {latex_escape(note)} \\\\"
        for label, careflow_value, meditrack_value, note in rows
    )


def render_scorecard_rows_block(context: dict[str, object]) -> str:
    return "\n".join(
        f"{latex_escape(row['dimension'])} & {latex_escape(row['careflow_text'])} & {latex_escape(row['meditrack_text'])} \\\\"
        for row in context["scorecard_rows"]
    )


def render_category_rows_block(rows: list[dict[str, object]], group_label: str) -> str:
    return "\n".join(
        (
            f"{latex_escape(display_group_label(row[group_label]))} & {latex_escape(format_pct(row['share_pct']))} & "
            f"{latex_escape(format_pct(row['completed_pct']))} & {latex_escape(format_pct(row['cancel_pct']))} \\\\"
        )
        for row in rows
    )


def render_region_rows_block(rows: list[dict[str, object]]) -> str:
    return "\n".join(f"{latex_escape(row['region'])} & {latex_escape(format_pct(row['share_pct']))} \\\\" for row in rows)


def build_report_context(results: AnalysisResults) -> dict[str, object]:
    now = datetime.now().astimezone()
    build_timestamp = now.isoformat(timespec="minutes")
    build_date = now.date().isoformat()
    analysis_run_label = now.strftime("%d %b %Y, %H:%M")
    registered_profile = results.meditrack_format_profile.loc["RegisteredAt"]
    context: dict[str, object] = {
        "build_timestamp": build_timestamp,
        "build_date": build_date,
        "analysis_run_label": analysis_run_label,
        "careflow_raw_rows": int(len(results.careflow_raw)),
        "meditrack_raw_rows": int(len(results.meditrack_raw)),
        "source_truth_files": [
            "data/careflow_north.csv",
            "data/meditrack_east.csv",
            "src/analyse.py",
            "src/reporting.py",
            "docs/methodology.md",
            "report/mediflow_report.tex",
            "report/mediflow_slides.tex",
        ],
        "foundation_points": [
            "We tested candidate file encodings to find an import setup that preserved the raw values.",
            "We read date columns as text first to find the real source formats before parsing them.",
            "We measured the slash and dash populations to find how mixed the messy date fields were.",
            "We separated exact duplicate rows from duplicate case IDs to find the true case grain.",
            "We marked risky metrics as exploratory to find which comparisons were safe to treat as headline results.",
            "We generated report facts from the script to keep the written outputs aligned with the current run.",
        ],
        "current_run_highlights": build_current_run_highlights(results),
        "careflow_metrics": results.careflow_metrics,
        "meditrack_metrics": results.meditrack_metrics,
        "scorecard_rows": results.scorecard_rows,
        "careflow_category_rows": build_category_summary(results.careflow, "TRACK", "CARE_REF", "Completed"),
        "meditrack_category_rows": build_category_summary(results.meditrack, "CareGroup", "RefNo", "Done"),
        "careflow_region_rows": build_region_share_table(results.careflow_raw["ZIP_PAT"]),
        "meditrack_region_rows": build_region_share_table(results.meditrack_raw["PostalArea"]),
        "registered_at_format": {
            "slash_pct": float(registered_profile["slash_pct"]),
            "dash_pct": float(registered_profile["dash_pct"]),
        },
        "meditrack_duplicate_profile": results.meditrack_duplicate_profile,
        "figure_specs": FIGURE_SPECS,
        "foundation_markdown": build_foundation_markdown(results),
        "generated_dir": "output/generated",
        "master_report_path": "report/mediflow_report.tex",
        "master_slides_path": "report/mediflow_slides.tex",
    }
    context["auto_exec_summary"] = build_auto_exec_summary(results)
    context["auto_quality_summary"] = build_auto_quality_summary(results)
    context["auto_geo_summary"] = build_auto_geo_summary(context)
    return context


def itemize_block(items: list[str]) -> str:
    lines = [r"\begin{itemize}"]
    for item in items:
        lines.append(f"  \\item {latex_escape(item)}")
    lines.append(r"\end{itemize}")
    return "\n".join(lines)


def render_macros_tex(context: dict[str, object]) -> str:
    careflow_metrics = context["careflow_metrics"]
    meditrack_metrics = context["meditrack_metrics"]
    duplicate_profile = context["meditrack_duplicate_profile"]
    registered_profile = context["registered_at_format"]
    careflow_region_rows = {row["region"]: row["share_pct"] for row in context["careflow_region_rows"]}
    meditrack_region_rows = {row["region"]: row["share_pct"] for row in context["meditrack_region_rows"]}
    return "\n\n".join(
        [
            define_value_macro("MediFlowBuildDate", context["build_date"]),
            define_value_macro("MediFlowBuildTimestamp", context["build_timestamp"]),
            define_value_macro("MediFlowAnalysisRunLabel", context["analysis_run_label"]),
            define_value_macro("MediFlowAutoTag", AUTO_TAG),
            r"\newcommand{\MediFlowContextPath}{\detokenize{../output/report_context.json}}",
            r"\newcommand{\MediFlowGeneratedDir}{\detokenize{../output/generated}}",
            define_value_macro("MediFlowCareFlowRawRows", format_int(context["careflow_raw_rows"])),
            define_value_macro("MediFlowMediTrackRawRows", format_int(context["meditrack_raw_rows"])),
            define_value_macro("MediFlowCareFlowRegisteredCases", format_int(careflow_metrics["registered_cases"])),
            define_value_macro("MediFlowMediTrackRegisteredCases", format_int(meditrack_metrics["registered_cases"])),
            define_value_macro("MediFlowCareFlowFinishedCases", format_int(careflow_metrics["completed_cases"])),
            define_value_macro("MediFlowMediTrackFinishedCases", format_int(meditrack_metrics["completed_cases"])),
            define_value_macro("MediFlowCareFlowFinishedPct", format_pct(careflow_metrics["completed_pct"])),
            define_value_macro("MediFlowMediTrackFinishedPct", format_pct(meditrack_metrics["completed_pct"])),
            define_value_macro("MediFlowCareFlowOpenPct", format_pct(careflow_metrics["open_pct"])),
            define_value_macro("MediFlowMediTrackOpenPct", format_pct(meditrack_metrics["open_pct"])),
            define_value_macro("MediFlowCareFlowCancelledPct", format_pct(careflow_metrics["cancelled_pct"])),
            define_value_macro("MediFlowMediTrackCancelledPct", format_pct(meditrack_metrics["cancelled_pct"])),
            define_value_macro("MediFlowCareFlowMedianDays", format_days(careflow_metrics["median_duration_days"])),
            define_value_macro("MediFlowMediTrackMedianDays", format_days(meditrack_metrics["median_duration_days"])),
            define_value_macro("MediFlowCareFlowMonthCoverage", careflow_metrics["temporal_coverage_text"]),
            define_value_macro("MediFlowMediTrackMonthCoverage", meditrack_metrics["temporal_coverage_text"]),
            define_value_macro("MediFlowCareFlowLogicalOrderPct", format_pct(careflow_metrics["logical_order_pct"])),
            define_value_macro("MediFlowMediTrackLogicalOrderPct", format_pct(meditrack_metrics["logical_order_pct"])),
            define_value_macro("MediFlowCareFlowInversionPct", format_pct(careflow_metrics["inversion_pct"], decimals=3)),
            define_value_macro("MediFlowMediTrackInversionPct", format_pct(meditrack_metrics["inversion_pct"])),
            define_value_macro("MediFlowMediTrackSlashPct", format_pct(registered_profile["slash_pct"])),
            define_value_macro("MediFlowMediTrackDashPct", format_pct(registered_profile["dash_pct"])),
            define_value_macro("MediFlowMediTrackExactDuplicateRows", format_int(duplicate_profile["exact_duplicate_rows"])),
            define_value_macro("MediFlowMediTrackCaseRowsRemoved", format_int(duplicate_profile["case_rows_removed"])),
            define_value_macro("MediFlowCareFlowHovedstadenPct", format_pct(careflow_region_rows["Hovedstaden"])),
            define_value_macro("MediFlowCareFlowSjaellandPct", format_pct(careflow_region_rows["Sjaelland"])),
            define_value_macro("MediFlowMediTrackHovedstadenPct", format_pct(meditrack_region_rows["Hovedstaden"])),
            define_value_macro("MediFlowMediTrackSjaellandPct", format_pct(meditrack_region_rows["Sjaelland"])),
            define_block_macro("MediFlowFoundationPoints", itemize_block(context["foundation_points"])),
            define_block_macro("MediFlowCurrentRunHighlights", itemize_block(context["current_run_highlights"])),
            define_block_macro("MediFlowKpiRows", render_kpi_rows_block(context)),
            define_block_macro("MediFlowScorecardRows", render_scorecard_rows_block(context)),
            define_block_macro("MediFlowCareFlowCategoryRows", render_category_rows_block(context["careflow_category_rows"], "TRACK")),
            define_block_macro("MediFlowMediTrackCategoryRows", render_category_rows_block(context["meditrack_category_rows"], "CareGroup")),
            define_block_macro("MediFlowCareFlowRegionRows", render_region_rows_block(context["careflow_region_rows"])),
            define_block_macro("MediFlowMediTrackRegionRows", render_region_rows_block(context["meditrack_region_rows"])),
            define_block_macro("MediFlowAutoExecSummary", latex_escape(context["auto_exec_summary"])),
            define_block_macro("MediFlowAutoQualitySummary", latex_escape(context["auto_quality_summary"])),
            define_block_macro("MediFlowAutoGeoSummary", latex_escape(context["auto_geo_summary"])),
        ]
    )


def render_kpi_table() -> str:
    lines = [
        "% AUTO-GENERATED KPI TABLE",
        r"{\small",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{4.0cm} >{\raggedleft\arraybackslash}p{2.2cm} >{\raggedleft\arraybackslash}p{2.2cm} X}",
        r"\toprule",
        r"Metric & CareFlow North & MediTrack East & Note \\",
        r"\midrule",
        r"\MediFlowKpiRows",
        r"\bottomrule",
        r"\end{tabularx}",
        r"}",
    ]
    return "\n".join(lines)


def render_scorecard_table() -> str:
    lines = [
        "% AUTO-GENERATED SCORECARD TABLE",
        r"\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{2.8cm} X X}",
        r"\toprule",
        r"Dimension & CareFlow North & MediTrack East \\",
        r"\midrule",
        r"\MediFlowScorecardRows",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines)


def render_category_table(group_label: str, rows_macro: str) -> str:
    lines = [
        "% AUTO-GENERATED CATEGORY TABLE",
        r"\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}p{4.2cm} >{\raggedleft\arraybackslash}p{2.0cm} >{\raggedleft\arraybackslash}p{2.0cm} >{\raggedleft\arraybackslash}p{2.0cm}}",
        r"\toprule",
        f"{latex_escape(group_label)} & Share & Completed & Cancelled \\\\",
        r"\midrule",
        rows_macro,
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines)


def render_region_table(title: str, rows_macro: str) -> str:
    lines = [
        "% AUTO-GENERATED REGION TABLE",
        r"\begin{tabular}{lr}",
        r"\toprule",
        f"{latex_escape(title)} & Share \\\\",
        r"\midrule",
        rows_macro,
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return "\n".join(lines)


def render_report_figure_block(spec: dict[str, str]) -> str:
    return "\n".join(
        [
            "% AUTO-GENERATED FIGURE BLOCK",
            r"\begin{figure}[H]",
            r"\centering",
            f"\\includegraphics[width=0.96\\textwidth]{{{spec['filename']}}}",
            f"\\caption{{{latex_escape(spec['title'])}. {latex_escape(spec['caption'])}}}",
            r"\end{figure}",
        ]
    )


def render_slide_source_truth_frame() -> str:
    return "\n".join(
        [
            r"\begin{frame}{Source of truth}",
            r"\small",
            r"\begin{itemize}",
            r"\item The numbers and tables in this deck come from the current Python analysis run.",
            r"\item Auto-generated text is marked so it can be reviewed if the data changes.",
            r"\item The PDF structure is editable, but the facts come from the pipeline output.",
            r"\end{itemize}",
            r"\end{frame}",
        ]
    )


def render_slide_kpi_snapshot_frame(context: dict[str, object]) -> str:
    careflow_metrics = context["careflow_metrics"]
    meditrack_metrics = context["meditrack_metrics"]
    return "\n".join(
        [
            r"\begin{frame}{2022 KPI overview}",
            r"\centering",
            r"\begin{tabular}{lrr}",
            r"\toprule",
            r"Metric & CareFlow & MediTrack \\",
            r"\midrule",
            f"Finished case rate & {format_pct(careflow_metrics['completed_pct'])} & {format_pct(meditrack_metrics['completed_pct'])} \\\\",
            f"Open rate & {format_pct(careflow_metrics['open_pct'])} & {format_pct(meditrack_metrics['open_pct'])} \\\\",
            f"Cancelled rate & {format_pct(careflow_metrics['cancelled_pct'])} & {format_pct(meditrack_metrics['cancelled_pct'])} \\\\",
            f"Median treatment time & {format_days(careflow_metrics['median_duration_days'])} & {format_days(meditrack_metrics['median_duration_days'])} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\vspace{0.6em}",
            r"\par\scriptsize \textbf{\MediFlowAutoTag} \MediFlowAutoExecSummary",
            r"\end{frame}",
        ]
    )


def render_slide_figure_frame(spec: dict[str, str]) -> str:
    return "\n".join(
        [
            f"\\begin{{frame}}{{{latex_escape(spec['title'])}}}",
            r"\centering",
            f"\\includegraphics[width=0.94\\textwidth,height=0.78\\textheight,keepaspectratio]{{{spec['filename']}}}",
            r"\vspace{0.4em}",
            f"\\par\\scriptsize {latex_escape(spec['caption'])}",
            r"\end{frame}",
        ]
    )


def render_slide_generated_interpretation_frame(context: dict[str, object]) -> str:
    return "\n".join(
        [
            r"\begin{frame}{Points to review}",
            r"\small",
            r"\textbf{\MediFlowAutoTag} \MediFlowAutoQualitySummary",
            r"\vspace{0.8em}",
            r"\par \MediFlowAutoGeoSummary",
            r"\end{frame}",
        ]
    )


def render_excel_formula_block(lines: list[str]) -> str:
    block = [
        r"\begin{minipage}[t]{\linewidth}",
        r"\raggedright\ttfamily\footnotesize",
    ]
    for index, line in enumerate(lines):
        suffix = r"\\" if index < len(lines) - 1 else ""
        block.append(f"{latex_escape(line)}{suffix}")
    block.append(r"\end{minipage}")
    return "\n".join(block)


def render_excel_parsing_section() -> str:
    clean_formula = render_excel_formula_block(
        [
            '=IF(A2=0,"",DATE(LEFT(TEXT(A2,"00000000"),4),',
            'MID(TEXT(A2,"00000000"),5,2),',
            'RIGHT(TEXT(A2,"00000000"),2)))',
        ]
    )
    mixed_formula = render_excel_formula_block(
        [
            '=IF(A2="","",IF(ISNUMBER(SEARCH("/",A2)),',
            'DATE(MID(A2,FIND("/",A2,FIND("/",A2)+1)+1,4),',
            'LEFT(A2,FIND("/",A2)-1),',
            'MID(A2,FIND("/",A2)+1,FIND("/",A2,FIND("/",A2)+1)-FIND("/",A2)-1)),',
            'DATE(RIGHT(LEFT(A2,10),4),MID(A2,4,2),LEFT(A2,2))))',
        ]
    )
    return "\n".join(
        [
            r"\noindent A practical part of the original exploration was helping a department turn exported date strings into usable Excel dates before any KPI work could start.",
            r"",
            r"\medskip",
            r"\begin{tabularx}{\textwidth}{@{}p{4.0cm}X@{}}",
            r"\toprule",
            r"\textbf{Pattern} & \textbf{Excel formula used in the exploration} \\",
            r"\midrule",
            r"Clean export (\texttt{YYYYMMDD}) & " + clean_formula + r" \\[0.8em]",
            r"Mixed export (slash / dash timestamps) & " + mixed_formula + r" \\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"",
            r"\noindent\small\textit{These formulas are kept as documentation of the exploration. The Python pipeline now mirrors the same logic, so Excel is not the source of truth for the final report.}",
        ]
    )


def render_slide_excel_parsing_frame() -> str:
    clean_formula = "\n".join(
        [
            r'{\ttfamily\scriptsize =IF(A2=0,"",DATE(LEFT(TEXT(A2,"00000000"),4),\\',
            r' MID(TEXT(A2,"00000000"),5,2),\\',
            r' RIGHT(TEXT(A2,"00000000"),2)))}',
        ]
    )
    mixed_formula = "\n".join(
        [
            r'{\ttfamily\scriptsize =IF(A2="","",IF(ISNUMBER(SEARCH("/",A2)),\\',
            r' DATE(MID(A2,FIND("/",A2,FIND("/",A2)+1)+1,4),\\',
            r' LEFT(A2,FIND("/",A2)-1),\\',
            r' MID(A2,FIND("/",A2)+1,FIND("/",A2,FIND("/",A2)+1)-FIND("/",A2)-1)),\\',
            r' DATE(RIGHT(LEFT(A2,10),4),MID(A2,4,2),LEFT(A2,2))))}',
        ]
    )
    return "\n".join(
        [
            r"\begin{frame}{Excel date parsing example}",
            r"\small",
            r"A practical part of the original exploration was helping users turn exported date strings into usable Excel dates before any KPI work could start.",
            r"",
            r"\vspace{0.4em}",
            r"\begin{columns}[T,onlytextwidth]",
            r"\column{0.48\textwidth}",
            r"\textbf{Clean export}",
            clean_formula,
            r"\column{0.48\textwidth}",
            r"\textbf{Mixed export}",
            mixed_formula,
            r"\end{columns}",
            r"",
            r"{\scriptsize The Python pipeline now uses the same logic. The Excel formulas stay here as documentation of the exploration, not as the source of truth.}",
            r"\end{frame}",
        ]
    )


def build_generated_snippets(context: dict[str, object]) -> dict[str, str]:
    snippets: dict[str, str] = {
        "00_document_macros.tex": with_generated_notice(render_macros_tex(context), "document macros"),
        "11_foundation_points.tex": with_generated_notice(r"\MediFlowFoundationPoints", "foundation points"),
        "12_current_run_highlights.tex": with_generated_notice(r"\MediFlowCurrentRunHighlights", "current-run highlights", needs_review=True),
        "13_excel_date_parsing.tex": with_generated_notice(render_excel_parsing_section(), "Excel date parsing note"),
        "20_kpi_table.tex": with_generated_notice(render_kpi_table(), "KPI table"),
        "21_scorecard_table.tex": with_generated_notice(render_scorecard_table(), "data-quality scorecard table"),
        "30_careflow_category_table.tex": with_generated_notice(render_category_table("TRACK", r"\MediFlowCareFlowCategoryRows"), "CareFlow category table"),
        "31_meditrack_category_table.tex": with_generated_notice(render_category_table("CareGroup", r"\MediFlowMediTrackCategoryRows"), "MediTrack category table"),
        "32_careflow_region_table.tex": with_generated_notice(render_region_table("CareFlow pool", r"\MediFlowCareFlowRegionRows"), "CareFlow region table"),
        "33_meditrack_region_table.tex": with_generated_notice(render_region_table("MediTrack pool", r"\MediFlowMediTrackRegionRows"), "MediTrack region table"),
        "40_exec_interpretation.tex": with_generated_notice(r"\MediFlowAutoExecSummary", "report interpretation text", needs_review=True),
        "41_quality_interpretation.tex": with_generated_notice(r"\MediFlowAutoQualitySummary", "quality interpretation text", needs_review=True),
        "42_geo_interpretation.tex": with_generated_notice(r"\MediFlowAutoGeoSummary", "geography interpretation text", needs_review=True),
        "70_slide_source_truth.tex": with_generated_notice(render_slide_source_truth_frame(), "slide source-of-truth frame"),
        "71_slide_kpi_snapshot.tex": with_generated_notice(render_slide_kpi_snapshot_frame(context), "slide KPI overview frame", needs_review=True),
        "72_slide_excel_date_parsing.tex": with_generated_notice(render_slide_excel_parsing_frame(), "slide Excel date parsing frame"),
        "99_slide_generated_interpretation.tex": with_generated_notice(render_slide_generated_interpretation_frame(context), "slide review points frame", needs_review=True),
    }
    for index, spec in enumerate(context["figure_specs"], start=50):
        stem = snippet_stem_for_figure(spec["filename"])
        snippets[f"{index:02d}_figure_{stem}.tex"] = with_generated_notice(render_report_figure_block(spec), f"figure block for {stem}")
        snippets[f"{index + 30:02d}_slide_{stem}.tex"] = with_generated_notice(render_slide_figure_frame(spec), f"slide frame for {stem}")
    return snippets


def write_generated_snippets(snippets: dict[str, str]) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    existing_files = {path.name for path in GENERATED_DIR.glob("*.tex")}
    for stale_name in existing_files - set(snippets):
        (GENERATED_DIR / stale_name).unlink()
    for filename, content in snippets.items():
        make_snippet_path(filename).write_text(content + "\n", encoding="utf-8")


def render_overleaf_master(master_path: Path) -> str:
    content = master_path.read_text(encoding="utf-8")
    replacements = {
        "../output/generated/": "generated/",
        "../output/figures/": "figures/",
        "../output/report_context.json": "report_context.json",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    return content


def render_overleaf_macros(macros_text: str) -> str:
    replacements = {
        "../output/report_context.json": "report_context.json",
        "../output/generated": "generated",
    }
    for old, new in replacements.items():
        macros_text = macros_text.replace(old, new)
    return macros_text


def export_overleaf_bundle(make_zip: bool = True) -> dict[str, object]:
    required_paths = [MASTER_REPORT_PATH, MASTER_SLIDES_PATH, CONTEXT_JSON_PATH, GENERATED_DIR, OUTPUT_DIR / "figures"]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        missing_text = ", ".join(str(path.relative_to(ROOT)).replace("\\", "/") for path in missing)
        raise FileNotFoundError(f"Cannot export Overleaf bundle because these paths are missing: {missing_text}")

    for export_dir in [LEGACY_OVERLEAF_DIR, OVERLEAF_DIR]:
        if export_dir.exists():
            shutil.rmtree(export_dir)
    OVERLEAF_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    OVERLEAF_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    OVERLEAF_MAIN_PATH.write_text(render_overleaf_master(MASTER_REPORT_PATH), encoding="utf-8")
    OVERLEAF_SLIDES_PATH.write_text(render_overleaf_master(MASTER_SLIDES_PATH), encoding="utf-8")
    shutil.copy2(CONTEXT_JSON_PATH, OVERLEAF_DIR / "report_context.json")

    for snippet_path in GENERATED_DIR.glob("*.tex"):
        content = snippet_path.read_text(encoding="utf-8")
        if snippet_path.name == "00_document_macros.tex":
            content = render_overleaf_macros(content)
        (OVERLEAF_GENERATED_DIR / snippet_path.name).write_text(content, encoding="utf-8")

    for spec in FIGURE_SPECS:
        source = OUTPUT_DIR / "figures" / spec["filename"]
        if source.exists():
            shutil.copy2(source, OVERLEAF_FIGURES_DIR / spec["filename"])

    readme_text = "\n".join(
        [
            "MediFlow Overleaf bundle",
            "",
            "Upload the contents of this folder to Overleaf and compile main.tex or slides.tex.",
            "",
            "Included files:",
            "- main.tex: editable article report entrypoint",
            "- slides.tex: editable slide deck entrypoint",
            "- generated/: analysis-driven LaTeX snippets",
            "- figures/: figure PNGs referenced by the editable documents",
            "- report_context.json: source-of-truth metrics for this export",
            "",
            "If you edit main.tex or slides.tex in Overleaf, keep the generated/ and figures/ folders in place.",
        ]
    )
    (OVERLEAF_DIR / "README.txt").write_text(readme_text + "\n", encoding="utf-8")

    archive_path: str | None = None
    if make_zip:
        archive_path = shutil.make_archive(str(OVERLEAF_ARCHIVE_BASE), "zip", root_dir=OVERLEAF_DIR)

    log(f"Exported Overleaf bundle to {OVERLEAF_DIR.relative_to(ROOT).as_posix()}")
    if archive_path:
        log(f"Created Overleaf archive at {Path(archive_path).relative_to(ROOT).as_posix()}")

    return {
        "bundle_dir": OVERLEAF_DIR,
        "archive_path": archive_path,
    }


def resolve_tex_command(command: str) -> str | None:
    resolved = shutil.which(command)
    if resolved:
        return resolved

    for bin_dir in WINDOWS_TEX_BIN_DIRS:
        candidate = bin_dir / f"{command}.exe"
        if candidate.exists():
            return str(candidate)

    return None


def detect_tex_engine() -> str | None:
    # Prefer direct PDF engines so local MiKTeX installs do not depend on latexmk + Perl.
    for candidate in ["pdflatex", "xelatex", "lualatex", "tectonic", "latexmk"]:
        resolved = resolve_tex_command(candidate)
        if resolved:
            return resolved
    return None


def cleanup_latex_auxiliary_files() -> None:
    for stem in [MASTER_REPORT_PATH.stem, MASTER_SLIDES_PATH.stem]:
        for extension in LATEX_AUXILIARY_EXTENSIONS:
            path = OUTPUT_DIR / f"{stem}{extension}"
            if path.exists():
                path.unlink()


def compile_tex_document(master_path: Path) -> dict[str, object]:
    engine = detect_tex_engine()
    if engine is None:
        return {"compiled": False, "engine": None, "reason": "No TeX compiler found on PATH or in the standard MiKTeX install location"}

    engine_name = Path(engine).stem.lower()

    try:
        if engine_name == "latexmk":
            subprocess.run(
                [engine, "-pdf", "-interaction=nonstopmode", f"-outdir={OUTPUT_DIR}", master_path.name],
                check=True,
                cwd=master_path.parent,
                capture_output=True,
                text=True,
            )
        elif engine_name == "tectonic":
            subprocess.run(
                [engine, master_path.name, "--outdir", str(OUTPUT_DIR)],
                check=True,
                cwd=master_path.parent,
                capture_output=True,
                text=True,
            )
        else:
            for _ in range(2):
                subprocess.run(
                    [engine, "-interaction=nonstopmode", "-output-directory", str(OUTPUT_DIR), master_path.name],
                    check=True,
                    cwd=master_path.parent,
                    capture_output=True,
                    text=True,
                )
        return {"compiled": True, "engine": engine_name, "reason": ""}
    except subprocess.CalledProcessError as exc:
        return {
            "compiled": False,
            "engine": engine_name,
            "reason": exc.stderr[-800:] if exc.stderr else exc.stdout[-800:],
        }


def compile_curated_documents() -> dict[str, object]:
    report_status = compile_tex_document(MASTER_REPORT_PATH)
    slides_status = compile_tex_document(MASTER_SLIDES_PATH)
    if report_status["compiled"] or slides_status["compiled"]:
        cleanup_latex_auxiliary_files()
    if report_status["compiled"]:
        log(f"Compiled {MASTER_REPORT_PATH.stem}.pdf via {report_status['engine']}")
    else:
        log(f"Skipped {MASTER_REPORT_PATH.stem}.pdf compilation: {report_status['reason']}")
    if slides_status["compiled"]:
        log(f"Compiled {MASTER_SLIDES_PATH.stem}.pdf via {slides_status['engine']}")
    else:
        log(f"Skipped {MASTER_SLIDES_PATH.stem}.pdf compilation: {slides_status['reason']}")
    return {"report_status": report_status, "slides_status": slides_status}


def write_generated_documents(results: AnalysisResults, compile_documents: bool = True) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_latex_auxiliary_files()

    context = build_report_context(results)
    snippets = build_generated_snippets(context)

    CONTEXT_JSON_PATH.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    write_generated_snippets(snippets)

    for stale_path in [LEGACY_REPORT_TEX_PATH, LEGACY_SLIDES_TEX_PATH]:
        if stale_path.exists():
            stale_path.unlink()

    log(f"Saved {CONTEXT_JSON_PATH.name}")
    log(f"Saved generated snippets to {GENERATED_DIR.relative_to(ROOT).as_posix()}")
    log(f"Editable report entrypoint: {MASTER_REPORT_PATH.relative_to(ROOT).as_posix()}")
    log(f"Editable slides entrypoint: {MASTER_SLIDES_PATH.relative_to(ROOT).as_posix()}")
    if compile_documents:
        statuses = compile_curated_documents()
        report_status = statuses["report_status"]
        slides_status = statuses["slides_status"]
    else:
        report_status = {"compiled": False, "engine": None, "reason": "Compilation skipped by caller"}
        slides_status = {"compiled": False, "engine": None, "reason": "Compilation skipped by caller"}

    return {
        "context": context,
        "snippets": snippets,
        "report_status": report_status,
        "slides_status": slides_status,
    }
