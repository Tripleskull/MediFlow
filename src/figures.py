"""Figure-drawing functions for the MediFlow pipeline.

Consumes the AnalysisResults dataclass from analyse.py and writes PNGs to
output/figures/. Kept separate from analyse.py so the metrics layer can be
read without scrolling past several hundred lines of matplotlib code.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from textwrap import fill

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
import numpy as np
import pandas as pd

from .analyse import (
    AnalysisResults,
    CAREFLOW_DATE_COLUMNS,
    FIG_DIR,
    MEDITRACK_DATE_COLUMNS,
    POSTCODE_REFERENCE_PATH,
    build_automation_profile,
    collapse_meditrack_status_for_comparison,
    log,
)
from .labels import display_group_label

POSTCODE_GEOJSON_PATH = Path(__file__).resolve().parent.parent / "data" / "postal_codes_denmark.geojson"

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CAREFLOW_STATUS_MONTHS = list(range(1, 12))
MEDITRACK_STATUS_MONTHS = list(range(1, 13))

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


def cleanup_stale_figure_files() -> None:
    if not FIG_DIR.exists():
        return
    for path in FIG_DIR.glob("*.png"):
        if path.name not in ACTIVE_FIGURE_FILENAMES:
            path.unlink()


def save_figure(fig: plt.Figure, filename: str) -> None:
    fig.savefig(FIG_DIR / filename, dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    log(f"Saved {filename}")


def scorecard_color(level: str) -> str:
    return {"ok": PALE_GREEN, "caution": PALE_YELLOW, "fail": PALE_RED}.get(level, "white")


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
