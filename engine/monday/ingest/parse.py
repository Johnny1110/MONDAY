"""Pure parse helpers for ingest adapters — ROC dates + messy numerics (stdlib, unit-tested).

TW official sources speak Republic-of-China dates (民國: year + 1911) and human-formatted
numbers ("2,355.00", "+60.00", "--"). Normalising those is "same input → same output, must have
a unit test" logic, so it lives here in the platform (§2), separate from the HTTP side effects.
"""

from __future__ import annotations


def roc_to_iso(s) -> str | None:
    """ROC date → ISO. '1150612' or '115/06/12' → '2026-06-12'. None if unparseable."""
    if not s:
        return None
    t = str(s).strip()
    if "/" in t:
        parts = t.split("/")
        if len(parts) != 3:
            return None
        try:
            return f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            return None
    t = t.replace("-", "")
    if not t.isdigit() or len(t) < 6:
        return None
    try:
        return f"{int(t[:-4]) + 1911:04d}-{int(t[-4:-2]):02d}-{int(t[-2:]):02d}"
    except ValueError:
        return None


def num(s) -> float | None:
    """Messy numeric → float or None. Handles commas, leading '+', spaces, and the various
    'no value' tokens TW sources use ('--', '', 'X')."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().replace(",", "").replace("+", "")
    if t in ("", "--", "---", "X", "x", "N/A", "null"):
        return None
    try:
        return float(t)
    except ValueError:
        return None
