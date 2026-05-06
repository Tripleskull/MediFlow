"""Reusable formatting and normalisation helpers.

These were originally duplicated across analyse.py and reporting.py. The two
copies of format_days disagreed on the suffix ("48 d" in figure cells, "48
days" in narrative prose); the consolidated version below honours both via
the abbreviated flag, defaulting to the long form used in narrative text.
"""

from __future__ import annotations

import pandas as pd


def safe_pct(numerator: float, denominator: float) -> float:
    """Return 100 * numerator / denominator, or 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return 100.0 * float(numerator) / float(denominator)


def format_pct(value: float, decimals: int = 1) -> str:
    """Format a value as a percentage string with a fixed decimal count."""
    return f"{value:.{decimals}f}%"


def format_int(value: int | float) -> str:
    """Format an integer-like value with thousand separators."""
    return f"{int(value):,}"


def format_days(value: float | int | None, *, abbreviated: bool = False) -> str:
    """Format a day count as text.

    Returns "N/A" when the input is None or NaN. Pass abbreviated=True for
    space-constrained figure annotations (renders as "48 d" instead of
    "48 days").
    """
    if value is None or pd.isna(value):
        return "N/A"
    n = int(round(float(value)))
    suffix = "d" if abbreviated else "days"
    return f"{n} {suffix}"


def normalise_text_series(series: pd.Series) -> pd.Series:
    """Coerce a series to nullable string and blank out empty/<NA> sentinels."""
    cleaned = series.astype("string").str.strip()
    cleaned = cleaned.mask(cleaned.eq(""))
    cleaned = cleaned.mask(cleaned.eq("<NA>"))
    return cleaned
