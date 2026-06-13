"""Uniform list pagination + sorting (invariant 3).

Every list endpoint returns the SAME envelope — ``{items, page, page_size, total,
has_more}`` — so an agent learns the shape once and reuses it across universe / prices /
signals / recommendations / ledger. Pure + stdlib, so it is unit-testable on its own
(copied verbatim from Sunday — proven; don't reinvent).
"""

from __future__ import annotations

from typing import Any

MAX_PAGE_SIZE = 500


def clamp_page(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 50), MAX_PAGE_SIZE))
    return page, page_size


def paginate(items: list[Any], page: int = 1, page_size: int = 50) -> dict:
    """Slice ``items`` into the standard page envelope."""
    page, page_size = clamp_page(page, page_size)
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": start + page_size < total,
    }


def sort_by(items: list[dict], key: str | None, order: str = "desc") -> list[dict]:
    """Sort dict rows by ``key``; missing/None values always sink to the end (regardless
    of order), so a row with no value never tops a sort."""
    if not key:
        return list(items)
    reverse = (order or "desc").lower() != "asc"
    present = [it for it in items if it.get(key) is not None]
    missing = [it for it in items if it.get(key) is None]
    present.sort(key=lambda it: it.get(key), reverse=reverse)
    return present + missing
