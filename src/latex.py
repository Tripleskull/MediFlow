"""LaTeX text builders for the generated MediFlow snippets.

These functions return strings — they do no I/O and have no knowledge of
output paths. reporting.py orchestrates context assembly and writes the
returned snippets to disk; this module is the pure rendering layer.
"""

from __future__ import annotations

from .formats import format_days, format_int, format_pct
from .labels import display_group_label

AUTO_TAG = "[AUTO-GENERATED INTERPRETATION]"
GENERATED_REFRESH_NOTE = "Refresh with python -m src.cli analyse --no-compile."


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


def with_generated_notice(content: str, label: str, needs_review: bool = False) -> str:
    lines = [
        f"% AUTO-GENERATED: {label}",
        f"% {GENERATED_REFRESH_NOTE}",
    ]
    if needs_review:
        lines.append("% Review this wording if the data changes.")
    lines.append(content)
    return "\n".join(lines)


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


def itemize_block(items: list[str]) -> str:
    lines = [r"\begin{itemize}"]
    for item in items:
        lines.append(f"  \\item {latex_escape(item)}")
    lines.append(r"\end{itemize}")
    return "\n".join(lines)


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


