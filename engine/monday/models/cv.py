"""Purged + embargo walk-forward CV (whitepaper §5.4) — pure stdlib.

A sample's label at date t spans [t, t+H], so it leaks into any validation block overlapping that
window; plain k-fold inflates IC and the live model collapses (§4.2/§9 — the #1 scientific risk).
Walk-forward validates on a FUTURE block and trains only on the PAST, separated by a gap of
``horizon + embargo`` dates (purge the label-overlap, embargo a safety margin). Returns
(train_dates, val_dates) per split; the caller maps rows to folds by date membership.
"""

from __future__ import annotations


def purged_walk_forward(dates: list[str], n_splits: int = 4, horizon: int = 20,
                        embargo: int = 5) -> list[tuple[list[str], list[str]]]:
    """Expanding-window walk-forward over the unique sorted dates. Split k validates on block k+1
    and trains on everything strictly before it minus a (horizon+embargo) purge gap."""
    uniq = sorted(set(dates))
    n = len(uniq)
    if n_splits < 1 or n < n_splits + 1:
        return []
    fold = n // (n_splits + 1)
    gap = horizon + embargo
    splits: list[tuple[list[str], list[str]]] = []
    for k in range(1, n_splits + 1):
        v0 = k * fold
        v1 = (k + 1) * fold if k < n_splits else n
        val = uniq[v0:v1]
        train = uniq[:max(0, v0 - gap)]      # drop train dates whose [t,t+H] reaches the val block
        if train and val:
            splits.append((train, val))
    return splits
