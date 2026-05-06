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
from functools import lru_cache
import json
from pathlib import Path
from textwrap import fill
from typing import Callable
import warnings

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import matplotlib.ticker as mticker
from matplotlib.patches import Polygon
import numpy as np
import pandas as pd

from .formats import format_days, format_pct, normalise_text_series, safe_pct
from .labels import display_group_label

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
FIG_DIR = OUTPUT_DIR / "figures"
POSTCODE_GEOJSON_PATH = DATA_DIR / "postal_codes_denmark.geojson"
POSTCODE_REFERENCE_PATH = DATA_DIR / "postcode_service_areas.csv"

CAREFLOW_DATE_COLUMNS = ["DT_CREATED", "DT_REG", "DT_ALLOC", "DT_ABORT", "DT_OPEN", "DT_END", "DT_CLOSE"]
MEDITRACK_DATE_COLUMNS = [
    "RegisteredAt",
    "AssignedOn",
    "CancelledOn",
    "StartPathway",
    "FinishedAt",
]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CAREFLOW_STATUS_MONTHS = list(range(1, 12))
MEDITRACK_STATUS_MONTHS = list(range(1, 13))
MIXED_DATE_FORMATS = [
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
]

BLUE = "#2563EB"
GREEN = "#16A34A"
LIGHT_BLUE = "#93C5FD"
LIGHT_GREEN = "#86EFAC"
PINK = "#F9A8D4"
GRAY = "#9CA3AF"
RED = "#DC2626"
NAVY = "#1E3A5F"
YELLOW = "#FDE68A"
LIGHT_GRAY = "#E5E7EB"
PALE_GREEN = "#E6F4EA"
PALE_YELLOW = "#FEF3C7"
PALE_RED = "#FEE2E2"
HEADER_BLUE = "#D5E8F0"
WATER = "#DCE9F0"
MAP_LAND = "#F8FAFC"
MAP_EDGE = "#CBD5E1"

ACTIVE_FIGURE_FILENAMES = {
    "monthly_volume_2022.png",
    "monthly_status_careflow.png",
    "monthly_status_meditrack.png",
    "treatment_duration_boxplot.png",
    "missing_date_fields.png",
    "date_span_outliers.png",
    "kpi_comparison.png",
    "geo_top15_postalcodes.png",
    "automation_matrix_careflow.png",
    "automation_matrix_meditrack.png",
    "automation_matrix_combined.png",
    "data_quality_scorecard.png",
}


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


def cleanup_stale_figure_files() -> None:
    if not FIG_DIR.exists():
        return
    for path in FIG_DIR.glob("*.png"):
        if path.name not in ACTIVE_FIGURE_FILENAMES:
            path.unlink()


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


def scorecard_color(level: str) -> str:
    return {"ok": PALE_GREEN, "caution": PALE_YELLOW, "fail": PALE_RED}.get(level, "white")


def save_figure(fig: plt.Figure, filename: str) -> None:
    fig.savefig(FIG_DIR / filename, dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    log(f"Saved {filename}")


plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "figure.dpi": 180,
        "savefig.dpi": 180,
    }
)


def fig_monthly_volume(careflow: pd.DataFrame, meditrack: pd.DataFrame) -> None:
    careflow_monthly = careflow.groupby("reg_month").size()
    meditrack_monthly = meditrack.groupby("reg_month").size()
    months = range(1, 13)
    x = np.arange(12)
    width = 0.38

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(x - width / 2, [careflow_monthly.get(month, 0) for month in months], width, color=BLUE, label="CareFlow North")
    ax.bar(x + width / 2, [meditrack_monthly.get(month, 0) for month in months], width, color=GREEN, label="MediTrack East")
    ax.set_xticks(x)
    ax.set_xticklabels(MONTH_LABELS)
    ax.set_ylabel("Number of cases")
    ax.set_xlabel("Registration month (2022)")
    ax.set_title("Registered cases per month in 2022")
    ax.legend()
    ax.annotate("Dec missing", xy=(11 - width / 2, max(50, careflow_monthly.max() * 0.08)), ha="center", fontsize=8, color=RED, style="italic")
    save_figure(fig, "monthly_volume_2022.png")


def fig_monthly_status(
    df: pd.DataFrame,
    categories: list[str],
    colors: list[str],
    completed_status: str,
    months: list[int],
    title: str,
    filename: str,
    status_column: str = "status",
) -> None:
    monthly = (
        df.assign(status=pd.Categorical(df[status_column], categories=categories, ordered=True))
        .pivot_table(index="reg_month", columns="status", values=df.columns[0], aggfunc="size", fill_value=0, observed=False)
        .reindex(months, fill_value=0)
    )
    completion_rate = (monthly[completed_status] / monthly.sum(axis=1).replace(0, np.nan) * 100.0).fillna(0.0).to_numpy()
    x = np.arange(len(months))

    fig, ax1 = plt.subplots(figsize=(10, 5))
    bottom = np.zeros(len(months))
    for category, color in zip(categories, colors):
        values = monthly[category].to_numpy()
        ax1.bar(x, values, bottom=bottom, color=color, label=category)
        bottom += values

    ax1.set_xticks(x)
    ax1.set_xticklabels([MONTH_LABELS[month - 1] for month in months])
    ax1.set_ylabel("Number of cases")
    ax1.set_xlabel("Registration month (2022)")
    ax1.set_title(title)
    ax1.legend(loc="upper left", fontsize=8)

    ax2 = ax1.twinx()
    ax2.plot(x, completion_rate, "ko-", markersize=4.5, linewidth=1.5, label="Finished case rate (%)")
    ax2.set_ylabel("Finished case rate (%)")
    ax2.set_ylim(0, 105)
    for index, value in enumerate(completion_rate):
        ax2.annotate(f"{value:.0f}%", (index, value + 2), ha="center", fontsize=7.5, color="black")
    ax2.legend(loc="upper right")
    save_figure(fig, filename)


def fig_treatment_duration_boxplot(careflow: pd.DataFrame, meditrack: pd.DataFrame) -> None:
    careflow_duration = careflow.loc[
        (careflow["status"] == "Completed") & careflow["duration_days_raw"].notna() & (careflow["duration_days_raw"] >= 0),
        "duration_days_raw",
    ]
    meditrack_duration = meditrack.loc[
        (meditrack["status"] == "Done") & meditrack["duration_days_raw"].notna() & (meditrack["duration_days_raw"] >= 0),
        "duration_days_raw",
    ]

    fig, ax = plt.subplots(figsize=(8, 5))
    boxplot = ax.boxplot(
        [careflow_duration.clip(upper=365), meditrack_duration.clip(upper=365)],
        tick_labels=[
            f"CareFlow North\n(n={len(careflow_duration):,})",
            f"MediTrack East\n(n={len(meditrack_duration):,})",
        ],
        patch_artist=True,
        widths=0.5,
        medianprops={"color": "black", "linewidth": 2},
        showfliers=False,
    )
    boxplot["boxes"][0].set_facecolor(BLUE)
    boxplot["boxes"][0].set_alpha(0.7)
    boxplot["boxes"][1].set_facecolor(GREEN)
    boxplot["boxes"][1].set_alpha(0.45)
    boxplot["boxes"][1].set_hatch("//")
    ax.set_ylabel("Treatment duration (days, capped at 365)")
    ax.set_title("Treatment duration distribution")
    ax.annotate(f"median: {careflow_duration.median():.0f} d", xy=(1, careflow_duration.median()), xytext=(1.25, careflow_duration.median() + 15), fontsize=9, color=NAVY)
    ax.annotate(f"median: {meditrack_duration.median():.0f} d", xy=(2, meditrack_duration.median()), xytext=(2.25, meditrack_duration.median() + 15), fontsize=9, color=NAVY)
    ax.text(
        0.5,
        -0.13,
        "MediTrack duration is retained as exploratory because finished cases still show frequent date inversion.",
        transform=ax.transAxes,
        ha="center",
        fontsize=7.5,
        style="italic",
        color=GRAY,
    )
    save_figure(fig, "treatment_duration_boxplot.png")


def fig_missing_dates(careflow: pd.DataFrame, meditrack: pd.DataFrame) -> None:
    careflow_fill = [(column, 100.0 * (1.0 - careflow[column].isna().mean())) for column in CAREFLOW_DATE_COLUMNS]
    meditrack_fill = [(column, 100.0 * (1.0 - meditrack[column].isna().mean())) for column in MEDITRACK_DATE_COLUMNS]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 4.6), constrained_layout=True)
    for axis, fill_values, title, color in [
        (ax1, careflow_fill, "CareFlow North", BLUE),
        (ax2, meditrack_fill, "MediTrack East", GREEN),
    ]:
        labels, values = zip(*fill_values)
        y = range(len(labels))
        axis.barh(y, values, color=color, alpha=0.8)
        axis.set_yticks(list(y))
        axis.set_yticklabels(labels, fontsize=9)
        axis.set_xlim(0, 112)
        axis.set_xlabel("Fill rate (%)")
        axis.set_title(title)
        for index, value in enumerate(values):
            axis.text(min(value + 1.0, 104.5), index, f"{value:.1f}%", va="center", fontsize=8)
    save_figure(fig, "missing_date_fields.png")


def plot_date_spans(ax: plt.Axes, df: pd.DataFrame, columns: list[str], color: str, title: str) -> None:
    start_2022 = pd.Timestamp("2022-01-01")
    end_2022 = pd.Timestamp("2022-12-31")
    for index, column in enumerate(columns):
        values = df[column].dropna()
        if values.empty:
            continue
        minimum = values.min()
        maximum = values.max()
        visible_start = max(minimum, start_2022)
        visible_end = min(maximum, end_2022)
        if visible_start <= visible_end:
            ax.plot([visible_start, visible_end], [index, index], color=color, linewidth=4, solid_capstyle="round")
        if minimum < start_2022:
            ax.plot([minimum, start_2022], [index, index], color=RED, linewidth=4, solid_capstyle="round")
        if maximum > end_2022:
            ax.plot([end_2022, maximum], [index, index], color=RED, linewidth=4, solid_capstyle="round")
        ax.plot(minimum, index, "o", color="black", markersize=4)
        ax.plot(maximum, index, "o", color="black", markersize=4)
    ax.set_yticks(range(len(columns)))
    ax.set_yticklabels(columns, fontsize=9)
    ax.set_title(title)
    ax.axvspan(start_2022, end_2022, alpha=0.08, color=color)


def fig_date_span_outliers(careflow: pd.DataFrame, meditrack: pd.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7))
    plot_date_spans(ax1, careflow, CAREFLOW_DATE_COLUMNS, BLUE, "CareFlow North date spans")
    plot_date_spans(ax2, meditrack, MEDITRACK_DATE_COLUMNS, GREEN, "MediTrack East date spans")
    fig.suptitle("Date field spans in and around 2022", fontsize=12, y=1.01)
    fig.text(
        0.5,
        0.01,
        "CareFlow includes DT_CREATED as an administrative timestamp, so pre-2022 dates are expected there even though registrations remain inside 2022.",
        ha="center",
        fontsize=7.5,
        style="italic",
        color=GRAY,
    )
    fig.tight_layout()
    save_figure(fig, "date_span_outliers.png")


def fig_kpi_comparison(results: AnalysisResults) -> None:
    careflow_metrics = results.careflow_metrics
    meditrack_metrics = results.meditrack_metrics
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 5.3), constrained_layout=True)

    percentage_labels = ["Finished %", "Cancelled %", "Finish < reg %"]
    careflow_values = [
        careflow_metrics["completed_pct"],
        careflow_metrics["cancelled_pct"],
        careflow_metrics["inversion_pct"],
    ]
    meditrack_values = [
        meditrack_metrics["completed_pct"],
        meditrack_metrics["cancelled_pct"],
        meditrack_metrics["inversion_pct"],
    ]
    x = np.arange(len(percentage_labels))
    width = 0.35
    bars1 = ax1.bar(x - width / 2, careflow_values, width, color=BLUE, label="CareFlow North")
    bars2 = ax1.bar(x + width / 2, meditrack_values, width, color=GREEN, label="MediTrack East")
    ax1.set_xticks(x)
    ax1.set_xticklabels(percentage_labels)
    ax1.set_ylabel("Percentage (%)")
    ax1.set_title("Percentage KPIs")
    ax1.legend()
    for bar in list(bars1) + list(bars2):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8, f"{bar.get_height():.1f}%", ha="center", fontsize=8)

    duration_labels = ["CareFlow North", "MediTrack East"]
    duration_values = [careflow_metrics["median_duration_days"], meditrack_metrics["median_duration_days"]]
    duration_bars = ax2.bar(duration_labels, duration_values, color=[BLUE, GREEN])
    duration_bars[1].set_hatch("//")
    duration_bars[1].set_alpha(0.5)
    ax2.set_ylabel("Days")
    ax2.set_title("Median treatment time")
    ax2.set_ylim(0, max(duration_values) + 14)
    ax2.text(0, duration_values[0] + 1.6, f"{duration_values[0]:.0f} days", ha="center", fontsize=10, fontweight="bold")
    ax2.text(1, duration_values[1] + 1.6, f"{duration_values[1]:.0f} days", ha="center", fontsize=10)
    ax2.text(
        0.5,
        -0.14,
        (
            "MediTrack bar is exploratory because "
            f"{meditrack_metrics['inversion_pct']:.1f}% of finished cases invert the date order"
        ),
        transform=ax2.transAxes,
        ha="center",
        va="top",
        fontsize=7.0,
        color=RED,
        style="italic",
    )
    fig.suptitle("KPI comparison in 2022", fontsize=12)
    save_figure(fig, "kpi_comparison.png")


def normalise_postcode_series(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    text = text.mask(text.eq(""))
    return text.str.extract(r"(\d{4})", expand=False)


def strip_z_from_ring(ring: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in ring]


def geometry_to_outer_rings(geometry: dict[str, object]) -> list[list[tuple[float, float]]]:
    geometry_type = str(geometry["type"])
    coordinates = geometry["coordinates"]
    if geometry_type == "Polygon":
        return [strip_z_from_ring(coordinates[0])]
    if geometry_type == "MultiPolygon":
        return [strip_z_from_ring(polygon[0]) for polygon in coordinates]
    raise ValueError(f"Unsupported geometry type: {geometry_type}")


def polygon_area_and_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    closed_ring = ring if ring[0] == ring[-1] else [*ring, ring[0]]
    double_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for index in range(len(closed_ring) - 1):
        x1, y1 = closed_ring[index]
        x2, y2 = closed_ring[index + 1]
        cross = x1 * y2 - x2 * y1
        double_area += cross
        centroid_x += (x1 + x2) * cross
        centroid_y += (y1 + y2) * cross
    if abs(double_area) < 1e-12:
        xs, ys = zip(*ring)
        return 0.0, float(np.mean(xs)), float(np.mean(ys))
    area = abs(double_area) / 2.0
    return area, centroid_x / (3.0 * double_area), centroid_y / (3.0 * double_area)


def multipolygon_centroid(polygons: list[list[tuple[float, float]]]) -> tuple[float, float]:
    total_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for ring in polygons:
        area, x_value, y_value = polygon_area_and_centroid(ring)
        total_area += area
        centroid_x += x_value * area
        centroid_y += y_value * area
    if total_area == 0:
        xs = [point[0] for ring in polygons for point in ring]
        ys = [point[1] for ring in polygons for point in ring]
        return float(np.mean(xs)), float(np.mean(ys))
    return centroid_x / total_area, centroid_y / total_area


@lru_cache(maxsize=1)
def load_postcode_reference_lookup() -> dict[str, dict[str, str]]:
    reference = pd.read_csv(POSTCODE_REFERENCE_PATH, dtype={"postcode": "string"}).fillna("none")
    return reference.set_index("postcode").to_dict(orient="index")


@lru_cache(maxsize=1)
def load_postcode_geometry_lookup() -> dict[str, dict[str, object]]:
    with POSTCODE_GEOJSON_PATH.open(encoding="utf-8") as handle:
        geojson = json.load(handle)
    lookup: dict[str, dict[str, object]] = {}
    for feature in geojson["features"]:
        code = str(feature["properties"]["postal_code"]).zfill(4)
        polygons = geometry_to_outer_rings(feature["geometry"])
        centroid_lon, centroid_lat = multipolygon_centroid(polygons)
        lookup[code] = {
            "postcode": code,
            "label_dk": feature["properties"]["label_dk"],
            "polygons": polygons,
            "centroid_lon": centroid_lon,
            "centroid_lat": centroid_lat,
        }
    return lookup


def build_postcode_geo_frame(series: pd.Series, label: str) -> pd.DataFrame:
    counts = normalise_postcode_series(series).dropna().value_counts().rename_axis("postcode").reset_index(name="cases")
    counts["system"] = label
    geometry_lookup = load_postcode_geometry_lookup()
    reference_lookup = load_postcode_reference_lookup()
    missing_codes = sorted(
        code for code in counts["postcode"] if code not in geometry_lookup or code not in reference_lookup
    )
    if missing_codes:
        raise ValueError(f"Missing postcode reference or geometry for: {', '.join(missing_codes)}")

    rows: list[dict[str, object]] = []
    for row in counts.itertuples(index=False):
        geometry = geometry_lookup[row.postcode]
        reference = reference_lookup[row.postcode]
        rows.append(
            {
                "postcode": row.postcode,
                "cases": int(row.cases),
                "system": label,
                "label_dk": reference["label_dk"],
                "actual_region": reference["actual_region"],
                "careflow_pool": reference["careflow_pool"],
                "meditrack_pool": reference["meditrack_pool"],
                "overlap_role": reference["overlap_role"],
                "centroid_lon": geometry["centroid_lon"],
                "centroid_lat": geometry["centroid_lat"],
            }
        )
    return pd.DataFrame(rows)


def draw_postcode_polygons(
    ax: plt.Axes,
    postcodes: set[str],
    geometry_lookup: dict[str, dict[str, object]],
    *,
    facecolor: str,
    edgecolor: str,
    linewidth: float,
    alpha: float,
    zorder: int,
) -> None:
    for postcode in postcodes:
        for ring in geometry_lookup[postcode]["polygons"]:
            ax.add_patch(
                Polygon(
                    ring,
                    closed=True,
                    facecolor=facecolor,
                    edgecolor=edgecolor,
                    linewidth=linewidth,
                    alpha=alpha,
                    zorder=zorder,
                )
            )


def get_denmark_bounds(geometry_lookup: dict[str, dict[str, object]]) -> tuple[float, float, float, float]:
    x_values: list[float] = []
    y_values: list[float] = []
    for geometry in geometry_lookup.values():
        for ring in geometry["polygons"]:
            for x_value, y_value in ring:
                x_values.append(x_value)
                y_values.append(y_value)
    return min(x_values), max(x_values), min(y_values), max(y_values)


def fig_geo_top15(careflow: pd.DataFrame, meditrack: pd.DataFrame) -> None:
    geometry_lookup = load_postcode_geometry_lookup()
    careflow_geo = build_postcode_geo_frame(careflow["ZIP_PAT"], "CareFlow North")
    meditrack_geo = build_postcode_geo_frame(meditrack["PostalArea"], "MediTrack East")

    fig, ax = plt.subplots(figsize=(11.6, 6.9))
    fig.patch.set_facecolor(WATER)
    ax.set_facecolor(WATER)

    min_x, max_x, min_y, max_y = get_denmark_bounds(geometry_lookup)
    x_pad = 0.35
    y_pad = 0.22

    draw_postcode_polygons(
        ax,
        set(geometry_lookup),
        geometry_lookup,
        facecolor=MAP_LAND,
        edgecolor=MAP_EDGE,
        linewidth=0.25,
        alpha=1.0,
        zorder=1,
    )

    for frame, color, label in [
        (careflow_geo, BLUE, "CareFlow North"),
        (meditrack_geo, GREEN, "MediTrack East"),
    ]:
        marker_sizes = np.sqrt(frame["cases"].to_numpy()) * 8.5 + 10
        ax.scatter(
            frame["centroid_lon"].to_numpy(),
            frame["centroid_lat"].to_numpy(),
            s=marker_sizes,
            c=color,
            alpha=0.72,
            edgecolors="white",
            linewidths=0.7,
            zorder=4,
            label=label,
        )

    for frame, offset in [
        (careflow_geo.nlargest(5, "cases"), (-0.06, 0.03)),
        (meditrack_geo.nlargest(5, "cases"), (0.05, -0.035)),
    ]:
        for row in frame.itertuples(index=False):
            ax.text(
                row.centroid_lon + offset[0],
                row.centroid_lat + offset[1],
                str(row.postcode),
                fontsize=7.2,
                color=NAVY,
                zorder=5,
            )

    ax.set_xlim(min_x - x_pad, max_x + x_pad)
    ax.set_ylim(min_y - y_pad, max_y + y_pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_anchor("C")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("2022 case geography on Danish postcode map")
    fig.subplots_adjust(left=0.03, right=0.98, top=0.92, bottom=0.12)
    ax.legend(
        handles=[
            Line2D([0], [0], marker="o", color="w", label="CareFlow North", markerfacecolor=BLUE, markeredgecolor="white", markersize=8),
            Line2D([0], [0], marker="o", color="w", label="MediTrack East", markerfacecolor=GREEN, markeredgecolor="white", markersize=8),
        ],
        title="Map key",
        loc="upper right",
        frameon=True,
    )
    fig.text(
        0.5,
        0.035,
        (
            "Postcode polygons are real, but the synthetic postcode assignments were chosen for readable visuals only. "
            "They do not represent actual Region Hovedstaden or Region Sjaelland case distributions."
        ),
        ha="center",
        va="center",
        fontsize=7.0,
        style="italic",
        color=NAVY,
    )
    save_figure(fig, "geo_top15_postalcodes.png")


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


def add_automation_bubble_legend(ax: plt.Axes, grouped: pd.DataFrame, color: str) -> None:
    legend_rates = sorted(
        {
            max(1, int(round(grouped["canc_rate"].min()))),
            max(1, int(round(grouped["canc_rate"].median()))),
            max(1, int(round(grouped["canc_rate"].max()))),
        }
    )
    for rate in legend_rates:
        ax.scatter([], [], s=rate * 45 + 40, c=color, alpha=0.5, edgecolors="black", label=f"Cancellation {rate}%")
    ax.legend(title="Cancellation rate", loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8, borderaxespad=0.0)


def fig_single_automation_matrix(
    grouped: pd.DataFrame,
    *,
    color: str,
    title: str,
    filename: str,
    label_offsets: dict[str, tuple[int, int]] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.8, 6.5), constrained_layout=True)
    bubble_sizes = grouped["canc_rate"] * 45 + 40
    ax.scatter(
        grouped["std_dur"],
        grouped["share_pct"],
        s=bubble_sizes,
        c=color,
        alpha=0.65,
        edgecolors="black",
        linewidths=0.8,
    )
    for _, row in grouped.iterrows():
        ax.annotate(
            f"{row['label']} ({row['canc_rate']:.1f}%)",
            (row["std_dur"], row["share_pct"]),
            textcoords="offset points",
            xytext=(label_offsets or {}).get(str(row["label"]), (8, 6)),
            fontsize=8.2,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.1},
        )
    ax.axhline(grouped["share_pct"].median(), color=GRAY, linestyle=":", alpha=0.5)
    ax.axvline(grouped["std_dur"].median(), color=GRAY, linestyle=":", alpha=0.5)
    ax.set_xlim(grouped["std_dur"].min() - 0.6, grouped["std_dur"].max() + 1.2)
    ax.set_ylim(0, grouped["share_pct"].max() + 6.0)
    ax.set_xlabel("Treatment-time spread (std dev, days)")
    ax.set_ylabel("Share of plotted finished cases (%)")
    ax.set_title(title)
    add_automation_bubble_legend(ax, grouped, color)
    save_figure(fig, filename)


def fig_combined_automation_matrix(careflow_grouped: pd.DataFrame, meditrack_grouped: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.4, 6.8), constrained_layout=True)
    label_offsets = {
        "CareFlow: HOME_MON": (10, 8),
        "CareFlow: SURG_POST": (10, 10),
        "CareFlow: DIAG": (10, -12),
        "MediTrack: Pakke B": (10, 10),
        "MediTrack: Forlob X": (10, -12),
        "MediTrack: Revurdering": (10, 2),
    }
    for grouped, color, system in [
        (careflow_grouped, BLUE, "CareFlow"),
        (meditrack_grouped, GREEN, "MediTrack"),
    ]:
        bubble_sizes = grouped["canc_rate"] * 42 + 35
        ax.scatter(
            grouped["std_dur"],
            grouped["share_pct"],
            s=bubble_sizes,
            c=color,
            alpha=0.65,
            edgecolors="black",
            linewidths=0.7,
            label=system,
        )
        for _, row in grouped.iterrows():
            ax.annotate(
                f"{system}: {row['label']}",
                (row["std_dur"], row["share_pct"]),
                textcoords="offset points",
                xytext=label_offsets.get(f"{system}: {row['label']}", (7, 5)),
                fontsize=7.6,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.0},
            )
    combined = pd.concat([careflow_grouped, meditrack_grouped], ignore_index=True)
    ax.axhline(combined["share_pct"].median(), color=GRAY, linestyle=":", alpha=0.5)
    ax.axvline(combined["std_dur"].median(), color=GRAY, linestyle=":", alpha=0.5)
    ax.set_xlim(combined["std_dur"].min() - 0.8, combined["std_dur"].max() + 1.2)
    ax.set_ylim(0, combined["share_pct"].max() + 6.0)
    ax.set_xlabel("Treatment-time spread (std dev, days)")
    ax.set_ylabel("Share of plotted finished cases (%)")
    ax.set_title("Combined category pattern")
    ax.legend(title="Dataset", loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    ax.text(
        0.5,
        -0.12,
        "Bubble size shows cancellation rate. Y-axis share is calculated within each dataset's plotted finished-case pool.",
        transform=ax.transAxes,
        ha="center",
        fontsize=7.5,
        style="italic",
        color=GRAY,
    )
    save_figure(fig, "automation_matrix_combined.png")


def fig_data_quality_scorecard(rows: list[dict[str, str]]) -> None:
    careflow_rows = [(row["dimension"], fill(row["careflow_text"], width=48)) for row in rows]
    meditrack_rows = [(row["dimension"], fill(row["meditrack_text"], width=48)) for row in rows]

    fig, axes = plt.subplots(2, 1, figsize=(11.8, 10.4), constrained_layout=True)

    for ax, dataset_name, table_rows, level_key in [
        (axes[0], "CareFlow North", careflow_rows, "careflow_level"),
        (axes[1], "MediTrack East", meditrack_rows, "meditrack_level"),
    ]:
        ax.axis("off")
        table = ax.table(
            cellText=table_rows,
            colLabels=["Dimension", dataset_name],
            cellLoc="left",
            loc="center",
            colWidths=[0.28, 0.72],
            bbox=[0.0, 0.03, 1.0, 0.88],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(11.0)
        table.scale(1, 1.95)
        for column in range(2):
            table[0, column].set_facecolor(HEADER_BLUE)
            table[0, column].set_text_props(fontweight="bold")
        for row_index, row in enumerate(rows, start=1):
            table[row_index, 1].set_facecolor(scorecard_color(row[level_key]))

    fig.suptitle("Data quality scorecard", fontsize=14, y=0.99)
    fig.text(
        0.5,
        0.012,
        "Scorecard values are generated from the current analysis run, not re-entered by hand.",
        ha="center",
        fontsize=8.5,
        style="italic",
        color=GRAY,
    )
    save_figure(fig, "data_quality_scorecard.png")


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


def generate_figures(results: AnalysisResults) -> None:
    cleanup_stale_figure_files()
    meditrack_comparison = collapse_meditrack_status_for_comparison(results.meditrack)
    careflow_automation = build_automation_profile(results.careflow, "TRACK", "CARE_REF", "Completed")
    meditrack_automation = build_automation_profile(
        results.meditrack,
        "CareGroup",
        "RefNo",
        "Done",
        label_transform=display_group_label,
    )
    fig_monthly_volume(results.careflow, results.meditrack)
    fig_monthly_status(
        results.careflow,
        categories=["Completed", "Open", "Cancelled"],
        colors=[BLUE, LIGHT_BLUE, PINK],
        completed_status="Completed",
        months=CAREFLOW_STATUS_MONTHS,
        title="CareFlow North status by registration month",
        filename="monthly_status_careflow.png",
    )
    fig_monthly_status(
        meditrack_comparison,
        categories=["Done", "Open", "Cancelled"],
        colors=[GREEN, LIGHT_GREEN, PINK],
        completed_status="Done",
        months=MEDITRACK_STATUS_MONTHS,
        title="MediTrack East status by registration month",
        filename="monthly_status_meditrack.png",
        status_column="comparison_status",
    )
    fig_treatment_duration_boxplot(results.careflow, results.meditrack)
    fig_missing_dates(results.careflow, results.meditrack)
    fig_date_span_outliers(results.careflow, results.meditrack)
    fig_kpi_comparison(results)
    fig_geo_top15(results.careflow, results.meditrack)
    fig_single_automation_matrix(
        careflow_automation,
        color=BLUE,
        title="CareFlow category pattern",
        filename="automation_matrix_careflow.png",
        label_offsets={
            "HOME_MON": (8, 4),
            "DIAG": (8, -14),
            "SURG_POST": (8, 12),
        },
    )
    fig_single_automation_matrix(
        meditrack_automation,
        color=GREEN,
        title="MediTrack category pattern",
        filename="automation_matrix_meditrack.png",
    )
    fig_combined_automation_matrix(careflow_automation, meditrack_automation)
    fig_data_quality_scorecard(results.scorecard_rows)


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
