"""Display-label helpers for category values.

Both source systems use Forløb X / Y as pathway labels. The CSVs sometimes
arrive with mojibake ("ForlÃ¸b X") instead of the proper unicode form, so this
helper folds both into the same plain-ASCII display label for figures, tables,
and prose.
"""

from __future__ import annotations


def display_group_label(label: object) -> str:
    """Return a display-friendly group label.

    Forløb X / Forløb Y (in either proper unicode or common mojibake form) are
    folded to plain "Forlob X" / "Forlob Y". Other labels pass through
    unchanged.
    """
    text = str(label)
    if text.lower().startswith("forl") and text.endswith(" X"):
        return "Forlob X"
    if text.lower().startswith("forl") and text.endswith(" Y"):
        return "Forlob Y"
    return text
