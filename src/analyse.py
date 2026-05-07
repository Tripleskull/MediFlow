"""MediFlow analysis pipeline.

The final project is intentionally code-first, but the script preserves the
logic that came out of earlier exploratory work on heterogeneous operational
extracts: test encodings before standardising ingestion, inspect raw date text
before coercion, separate exact duplicates from duplicate case identifiers, and
label uncertain KPIs as exploratory instead of silently treating them as robust.

Run from the project root:
    python -m src.analyse
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import warnings

import numpy as np
import pandas as pd

from .formats import format_days, format_pct, normalise_text_series, safe_pct

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
FIG_DIR = OUTPUT_DIR / "figures"
POSTCODE_REFERENCE_PATH = DATA_DIR / "postcode_service_areas.csv"

CAREFLOW_DATE_COLUMNS = ["DT_CREATED", "DT_REG", "DT_ALLOC", "DT_ABORT", "DT_OPEN", "DT_END", "DT_CLOSE"]
MEDITRACK_DATE_COLUMNS = [
    "RegisteredAt",
    "AssignedOn",
    "CancelledOn",
    "StartPathway",
    "FinishedAt",
]
MIXED_DATE_FORMATS = [
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
]


@dataclass
class AnalysisResults:
    careflow_raw: pd.DataFrame
    careflow: pd.DataFrame
    meditrack_raw: pd.DataFrame
    meditrack_parsed: pd.DataFrame
    meditrack: pd.DataFrame
    careflow_metrics: dict[str, object]
    meditrack_metrics: dict[str, object]
    meditrack_format_profile: pd.DataFrame
    meditrack_duplicate_profile: dict[str, int]
    scorecard_rows: list[dict[str, str]]


def log(message: str) -> None:
    """Print ASCII-safe progress messages."""
    print(message)


def ensure_output_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def load_careflow_raw() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "careflow_north.csv")


def parse_careflow(raw_df: pd.DataFrame) -> pd.DataFrame:
    parsed = raw_df.copy()
    for column in CAREFLOW_DATE_COLUMNS:
        values = parsed[column].replace(0, np.nan)
        text = values.astype("Int64").astype(str).replace("<NA>", None)
        parsed[column] = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return parsed


def load_meditrack_raw() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "meditrack_east.csv", dtype=str)


def parse_mixed_datetime_series(series: pd.Series) -> pd.Series:
    text = normalise_text_series(series)
    parsed = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    remaining = text.notna()
    for fmt in MIXED_DATE_FORMATS:
        if not remaining.any():
            break
        current = pd.to_datetime(text.where(remaining), format=fmt, errors="coerce")
        matched = current.notna()
        parsed.loc[matched] = current.loc[matched]
        remaining &= ~matched
    if remaining.any():
        fallback = pd.to_datetime(text.where(remaining), errors="coerce", dayfirst=True)
        matched = fallback.notna()
        parsed.loc[matched] = fallback.loc[matched]
    return parsed.dt.normalize()


def parse_meditrack(raw_df: pd.DataFrame) -> pd.DataFrame:
    parsed = raw_df.copy()
    for column in parsed.columns:
        parsed[column] = normalise_text_series(parsed[column])
    for column in MEDITRACK_DATE_COLUMNS:
        parsed[column] = parse_mixed_datetime_series(parsed[column])
    parsed["CaseIdx"] = pd.to_numeric(parsed["CaseIdx"], errors="coerce")
    return parsed


def compute_parse_rate(raw_df: pd.DataFrame, parsed_df: pd.DataFrame, date_columns: list[str], clean_style: str) -> float:
    total_values = 0
    parsed_values = 0
    for column in date_columns:
        if clean_style == "careflow":
            source = raw_df[column].replace(0, np.nan)
            mask = source.notna()
        else:
            mask = normalise_text_series(raw_df[column]).notna()
        total_values += int(mask.sum())
        parsed_values += int(parsed_df.loc[mask, column].notna().sum())
    return safe_pct(parsed_values, total_values)


def analyse_meditrack_date_formats(raw_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for column in MEDITRACK_DATE_COLUMNS:
        text = normalise_text_series(raw_df[column]).dropna()
        total = int(text.shape[0])
        slash_count = int(text.str.contains("/", regex=False).sum())
        dash_count = int(text.str.contains("-", regex=False).sum())
        rows.append(
            {
                "column": column,
                "total": total,
                "slash_pct": safe_pct(slash_count, total),
                "dash_pct": safe_pct(dash_count, total),
            }
        )
    return pd.DataFrame(rows).set_index("column")


def profile_meditrack_duplicates(parsed_df: pd.DataFrame) -> dict[str, int]:
    without_exact = parsed_df.drop_duplicates().copy()
    duplicate_case_mask = without_exact["RefNo"].duplicated(keep=False)
    duplicate_case_groups = without_exact.loc[duplicate_case_mask].groupby("RefNo", dropna=False)
    conflicting_status_groups = int(
        sum(group["ClosedFlag"].dropna().nunique() > 1 for _, group in duplicate_case_groups)
    )
    final_case_level = without_exact.drop_duplicates(subset=["RefNo"], keep="first")
    return {
        "raw_rows": int(len(parsed_df)),
        "exact_duplicate_rows": int(parsed_df.duplicated().sum()),
        "rows_after_exact_dedup": int(len(without_exact)),
        "duplicate_case_groups": int(without_exact.loc[duplicate_case_mask, "RefNo"].nunique(dropna=True)),
        "duplicate_case_rows": int(duplicate_case_mask.sum()),
        "case_rows_removed": int(len(without_exact) - len(final_case_level)),
        "conflicting_status_groups": conflicting_status_groups,
    }


def clean_careflow(parsed_df: pd.DataFrame) -> pd.DataFrame:
    df = parsed_df.copy()
    df["DT_COMPLETE"] = df[["DT_END", "DT_CLOSE"]].max(axis=1)
    df["duration_days_raw"] = (df["DT_COMPLETE"] - df["DT_REG"]).dt.days
    df["duration_days"] = df["duration_days_raw"].clip(lower=0)
    df["status"] = "Open"
    df.loc[df["DT_COMPLETE"].notna(), "status"] = "Completed"
    df.loc[df["DT_ABORT"].notna(), "status"] = "Cancelled"
    df["reg_year"] = df["DT_REG"].dt.year
    df = df[df["reg_year"] == 2022].copy()
    df["reg_month"] = df["DT_REG"].dt.month
    df["reg_month_label"] = df["DT_REG"].dt.strftime("%b")
    return df


def collapse_meditrack_case_duplicates(parsed_df: pd.DataFrame) -> pd.DataFrame:
    df = parsed_df.drop_duplicates().copy()
    ranking_columns = MEDITRACK_DATE_COLUMNS + ["ClosedFlag", "CareGroup", "ClinicTag", "PostalArea", "CaseIdx"]
    df["completeness_score"] = df[ranking_columns].notna().sum(axis=1)
    df["status_rank"] = df["ClosedFlag"].map(
        {"Done": 4, "Cancelled": 3, "In Progress": 2, "Pending": 1, "Open": 0}
    ).fillna(-1)
    df = df.sort_values(
        by=[
            "RefNo",
            "completeness_score",
            "status_rank",
            "FinishedAt",
            "CancelledOn",
            "AssignedOn",
            "StartPathway",
            "RegisteredAt",
            "CaseIdx",
        ],
        ascending=[True, False, False, False, False, False, False, True, False],
        na_position="last",
    )
    df = df.drop_duplicates(subset=["RefNo"], keep="first").copy()
    return df.drop(columns=["completeness_score", "status_rank"])


def clean_meditrack(parsed_df: pd.DataFrame) -> pd.DataFrame:
    df = collapse_meditrack_case_duplicates(parsed_df)
    df["duration_days_raw"] = (df["FinishedAt"] - df["RegisteredAt"]).dt.days
    df["duration_days"] = df["duration_days_raw"].clip(lower=0)
    df["status"] = df["ClosedFlag"].fillna("Unknown")
    df["reg_year"] = df["RegisteredAt"].dt.year
    df = df[df["reg_year"] == 2022].copy()
    df["reg_month"] = df["RegisteredAt"].dt.month
    df["reg_month_label"] = df["RegisteredAt"].dt.strftime("%b")
    return df


def collapse_meditrack_status_for_comparison(df: pd.DataFrame) -> pd.DataFrame:
    collapsed = df.copy()
    collapsed["comparison_status"] = collapsed["status"].replace({"In Progress": "Open", "Pending": "Open", "Open": "Open"})
    return collapsed


def compute_careflow_metrics(raw_df: pd.DataFrame, clean_df: pd.DataFrame) -> dict[str, object]:
    completed_mask = clean_df["status"] == "Completed"
    cancelled_mask = clean_df["status"] == "Cancelled"
    open_mask = clean_df["status"] == "Open"
    inversion_base = clean_df["DT_COMPLETE"].notna() & clean_df["DT_REG"].notna()
    duration_base = completed_mask & clean_df["duration_days_raw"].notna() & (clean_df["duration_days_raw"] >= 0)
    logical_base = clean_df["DT_REG"].notna() & clean_df["DT_ALLOC"].notna()
    months_present = sorted(int(month) for month in clean_df["reg_month"].dropna().unique())

    return {
        "system": "CareFlow North",
        "registered_cases": int(len(clean_df)),
        "completed_cases": int(completed_mask.sum()),
        "completed_pct": safe_pct(completed_mask.sum(), len(clean_df)),
        "cancelled_cases": int(cancelled_mask.sum()),
        "cancelled_pct": safe_pct(cancelled_mask.sum(), len(clean_df)),
        "open_cases": int(open_mask.sum()),
        "open_pct": safe_pct(open_mask.sum(), len(clean_df)),
        "inversion_pct": safe_pct((clean_df.loc[inversion_base, "duration_days_raw"] < 0).sum(), inversion_base.sum()),
        "median_duration_days": float(clean_df.loc[duration_base, "duration_days_raw"].median()),
        "mean_duration_days": float(clean_df.loc[duration_base, "duration_days_raw"].mean()),
        "logical_order_pct": safe_pct(
            (clean_df.loc[logical_base, "DT_REG"] <= clean_df.loc[logical_base, "DT_ALLOC"]).sum(),
            logical_base.sum(),
        ),
        "parse_rate_pct": compute_parse_rate(raw_df, clean_df, CAREFLOW_DATE_COLUMNS, clean_style="careflow"),
        "months_present": months_present,
        "temporal_coverage_text": f"{len(months_present)}/12 months",
        "treatment_time_text": f"OK: median {format_days(clean_df.loc[duration_base, 'duration_days_raw'].median(), abbreviated=True)}",
        "duplicates_text": "OK: no duplicate case rows",
    }


def compute_meditrack_metrics(
    raw_df: pd.DataFrame,
    parsed_df: pd.DataFrame,
    clean_df: pd.DataFrame,
    duplicate_profile: dict[str, int],
) -> dict[str, object]:
    done_mask = clean_df["status"] == "Done"
    cancelled_mask = clean_df["status"] == "Cancelled"
    open_like_mask = clean_df["status"].isin(["Open", "Pending", "In Progress"])
    inversion_base = clean_df["FinishedAt"].notna() & clean_df["RegisteredAt"].notna()
    duration_base = done_mask & clean_df["duration_days_raw"].notna() & (clean_df["duration_days_raw"] >= 0)
    logical_base = clean_df["RegisteredAt"].notna() & clean_df["AssignedOn"].notna()
    months_present = sorted(int(month) for month in clean_df["reg_month"].dropna().unique())

    return {
        "system": "MediTrack East",
        "registered_cases": int(len(clean_df)),
        "completed_cases": int(done_mask.sum()),
        "completed_pct": safe_pct(done_mask.sum(), len(clean_df)),
        "cancelled_cases": int(cancelled_mask.sum()),
        "cancelled_pct": safe_pct(cancelled_mask.sum(), len(clean_df)),
        "open_cases": int(open_like_mask.sum()),
        "open_pct": safe_pct(open_like_mask.sum(), len(clean_df)),
        "inversion_pct": safe_pct((clean_df.loc[inversion_base, "duration_days_raw"] < 0).sum(), inversion_base.sum()),
        "median_duration_days": float(clean_df.loc[duration_base, "duration_days_raw"].median()),
        "mean_duration_days": float(clean_df.loc[duration_base, "duration_days_raw"].mean()),
        "logical_order_pct": safe_pct(
            (clean_df.loc[logical_base, "RegisteredAt"] <= clean_df.loc[logical_base, "AssignedOn"]).sum(),
            logical_base.sum(),
        ),
        "parse_rate_pct": compute_parse_rate(raw_df, parsed_df, MEDITRACK_DATE_COLUMNS, clean_style="meditrack"),
        "months_present": months_present,
        "temporal_coverage_text": f"{len(months_present)}/12 months",
        "treatment_time_text": f"Exploratory: median {format_days(clean_df.loc[duration_base, 'duration_days_raw'].median(), abbreviated=True)}",
        "duplicates_text": (
            "Resolved: "
            f"{duplicate_profile['exact_duplicate_rows']} exact rows + "
            f"{duplicate_profile['case_rows_removed']} extra case rows removed"
        ),
    }


def build_scorecard_rows(
    careflow_metrics: dict[str, object],
    meditrack_metrics: dict[str, object],
    format_profile: pd.DataFrame,
    duplicate_profile: dict[str, int],
) -> list[dict[str, str]]:
    registered_profile = format_profile.loc["RegisteredAt"]
    meditrack_format_text = (
        "Caution: mixed slash/dash timestamps "
        f"({registered_profile['slash_pct']:.1f}% slash, {registered_profile['dash_pct']:.1f}% dash)"
    )
    careflow_coverage_level = "ok" if len(careflow_metrics["months_present"]) == 12 else "caution"
    meditrack_logic_level = "ok" if meditrack_metrics["logical_order_pct"] >= 95 else "caution"
    meditrack_inversion_level = "fail" if meditrack_metrics["inversion_pct"] >= 5 else "caution"

    return [
        {
            "dimension": "Date format",
            "careflow_text": "OK: single YYYYMMDD format",
            "careflow_level": "ok",
            "meditrack_text": meditrack_format_text,
            "meditrack_level": "caution",
        },
        {
            "dimension": "Parse rate",
            "careflow_text": f"OK: {format_pct(careflow_metrics['parse_rate_pct'])}",
            "careflow_level": "ok",
            "meditrack_text": f"OK: {format_pct(meditrack_metrics['parse_rate_pct'])}",
            "meditrack_level": "ok",
        },
        {
            "dimension": "Reg <= assign",
            "careflow_text": f"OK: {format_pct(careflow_metrics['logical_order_pct'])}",
            "careflow_level": "ok",
            "meditrack_text": f"{'Caution' if meditrack_logic_level == 'caution' else 'OK'}: {format_pct(meditrack_metrics['logical_order_pct'])}",
            "meditrack_level": meditrack_logic_level,
        },
        {
            "dimension": "Finish before reg",
            "careflow_text": f"OK: {format_pct(careflow_metrics['inversion_pct'], decimals=3)}",
            "careflow_level": "ok",
            "meditrack_text": f"Fail: {format_pct(meditrack_metrics['inversion_pct'])}",
            "meditrack_level": meditrack_inversion_level,
        },
        {
            "dimension": "Treatment-time KPI",
            "careflow_text": str(careflow_metrics["treatment_time_text"]),
            "careflow_level": "ok",
            "meditrack_text": str(meditrack_metrics["treatment_time_text"]),
            "meditrack_level": "fail",
        },
        {
            "dimension": "Temporal coverage",
            "careflow_text": f"{'Caution' if careflow_coverage_level == 'caution' else 'OK'}: {len(careflow_metrics['months_present'])}/12 months",
            "careflow_level": careflow_coverage_level,
            "meditrack_text": f"OK: {len(meditrack_metrics['months_present'])}/12 months",
            "meditrack_level": "ok",
        },
        {
            "dimension": "Duplicates",
            "careflow_text": str(careflow_metrics["duplicates_text"]),
            "careflow_level": "ok",
            "meditrack_text": (
                "Fail: "
                f"{duplicate_profile['exact_duplicate_rows']} exact rows and "
                f"{duplicate_profile['case_rows_removed']} extra case rows required collapse"
            ),
            "meditrack_level": "fail",
        },
    ]


def build_automation_profile(
    df: pd.DataFrame,
    group_col: str,
    id_col: str,
    done_status: str,
    label_transform: Callable[[str], str] | None = None,
) -> pd.DataFrame:
    done = df.loc[
        (df["status"] == done_status) & df["duration_days_raw"].notna() & df["duration_days_raw"].between(0, 365)
    ].copy()
    grouped = done.groupby(group_col).agg(volume=(id_col, "size"), std_dur=("duration_days_raw", "std")).reset_index()
    grouped["std_dur"] = grouped["std_dur"].fillna(0.0)
    grouped["share_pct"] = grouped["volume"] / grouped["volume"].sum() * 100.0
    grouped["canc_rate"] = grouped[group_col].map(
        lambda value: safe_pct((df.loc[df[group_col] == value, "status"] == "Cancelled").sum(), (df[group_col] == value).sum())
    )
    grouped["label"] = grouped[group_col].astype(str)
    if label_transform is not None:
        grouped["label"] = grouped["label"].map(label_transform)
    return grouped


def build_foundation_markdown(results: AnalysisResults) -> str:
    careflow_metrics = results.careflow_metrics
    meditrack_metrics = results.meditrack_metrics
    registered_profile = results.meditrack_format_profile.loc["RegisteredAt"]
    duplicate_profile = results.meditrack_duplicate_profile
    return f"""# How this analysis was built

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

- CareFlow finished case rate (Completed): {careflow_metrics['completed_pct']:.1f}%
- CareFlow open rate at year end: {careflow_metrics['open_pct']:.1f}%
- CareFlow median treatment time: {careflow_metrics['median_duration_days']:.0f} days
- MediTrack finished case rate (Done): {meditrack_metrics['completed_pct']:.1f}%
- MediTrack finish-before-registration rate: {meditrack_metrics['inversion_pct']:.1f}%
- MediTrack RegisteredAt date styles: {registered_profile['slash_pct']:.1f}% slash, {registered_profile['dash_pct']:.1f}% dash
- MediTrack duplicate cleanup in the pipeline: {duplicate_profile['exact_duplicate_rows']} exact rows removed and {duplicate_profile['case_rows_removed']} extra case rows collapsed

## Plain-language read

CareFlow is the cleaner system for direct KPI comparison. It still has open cases at year end, and its admin dates can start before 2022, so the data is not unrealistically neat. MediTrack is useful for status and volume comparison, but its treatment-time measure is still only a rough check because finish dates often come before registration dates. The postcode map uses real postcode shapes, but the postcode choices are synthetic and were picked for visual separation rather than to reflect actual Region Hovedstaden or Region Sjaelland activity.
"""


def write_foundation_summary(results: AnalysisResults) -> Path:
    output_path = OUTPUT_DIR / "analysis_foundation.md"
    output_path.write_text(build_foundation_markdown(results), encoding="utf-8")
    log(f"Saved {output_path.name}")
    return output_path


def print_kpi_summary(results: AnalysisResults) -> None:
    careflow_metrics = results.careflow_metrics
    meditrack_metrics = results.meditrack_metrics
    print()
    print("=" * 64)
    print("KPI SUMMARY")
    print("=" * 64)
    print(f"{'':28s}{'CareFlow':>16s}{'MediTrack':>16s}")
    print(f"{'Registered cases (2022)':28s}{careflow_metrics['registered_cases']:>16,d}{meditrack_metrics['registered_cases']:>16,d}")
    print(f"{'Finished cases':28s}{careflow_metrics['completed_cases']:>16,d}{meditrack_metrics['completed_cases']:>16,d}")
    print(f"{'Finished case rate (%)':28s}{careflow_metrics['completed_pct']:>15.1f}%{meditrack_metrics['completed_pct']:>15.1f}%")
    print(f"{'Open (%)':28s}{careflow_metrics['open_pct']:>15.1f}%{meditrack_metrics['open_pct']:>15.1f}%")
    print(f"{'Cancelled (%)':28s}{careflow_metrics['cancelled_pct']:>15.1f}%{meditrack_metrics['cancelled_pct']:>15.1f}%")
    print(f"{'Median duration (days)':28s}{careflow_metrics['median_duration_days']:>16.0f}{meditrack_metrics['median_duration_days']:>16.0f}")
    print(f"{'Finish before registration (%)':28s}{careflow_metrics['inversion_pct']:>15.3f}%{meditrack_metrics['inversion_pct']:>15.1f}%")
    print("=" * 64)


def build_analysis_results() -> AnalysisResults:
    ensure_output_dirs()
    careflow_raw = load_careflow_raw()
    careflow_parsed = parse_careflow(careflow_raw)
    meditrack_raw = load_meditrack_raw()
    meditrack_parsed = parse_meditrack(meditrack_raw)
    careflow = clean_careflow(careflow_parsed)
    meditrack_format_profile = analyse_meditrack_date_formats(meditrack_raw)
    meditrack_duplicate_profile = profile_meditrack_duplicates(meditrack_parsed)
    meditrack = clean_meditrack(meditrack_parsed)
    careflow_metrics = compute_careflow_metrics(careflow_raw, careflow)
    meditrack_metrics = compute_meditrack_metrics(meditrack_raw, meditrack_parsed, meditrack, meditrack_duplicate_profile)
    scorecard_rows = build_scorecard_rows(careflow_metrics, meditrack_metrics, meditrack_format_profile, meditrack_duplicate_profile)
    return AnalysisResults(
        careflow_raw=careflow_raw,
        careflow=careflow,
        meditrack_raw=meditrack_raw,
        meditrack_parsed=meditrack_parsed,
        meditrack=meditrack,
        careflow_metrics=careflow_metrics,
        meditrack_metrics=meditrack_metrics,
        meditrack_format_profile=meditrack_format_profile,
        meditrack_duplicate_profile=meditrack_duplicate_profile,
        scorecard_rows=scorecard_rows,
    )


def run_analysis(
    generate_plots: bool = True,
    write_summary: bool = True,
    write_documents: bool = True,
    compile_documents: bool = True,
) -> AnalysisResults:
    log("Loading and analysing datasets...")
    results = build_analysis_results()
    log(f"CareFlow rows: {len(results.careflow):,}")
    log(f"MediTrack rows after case-level cleanup: {len(results.meditrack):,}")
    if write_summary:
        write_foundation_summary(results)
    if generate_plots:
        from .figures import generate_figures

        generate_figures(results)
    if write_documents:
        from .reporting import write_generated_documents

        write_generated_documents(results, compile_documents=compile_documents)
    print_kpi_summary(results)
    return results


def main() -> None:
    run_analysis(generate_plots=True, write_summary=True, write_documents=True, compile_documents=True)


if __name__ == "__main__":
    main()
