"""Cleaning, split-adjustment, and quality gates (whitepaper §4.2 — platform, pure logic).

Pure + stdlib so it is unit-testable anywhere (invariant 6). The quality gate never silently
feeds malformed bars into the model — bad rows are isolated and returned for the watchdog. The
liquidity filter is a HARD universe gate (a risk flag, not an alpha factor, §4.1): a 1-month
swing idea is meaningless in a name the User can't get in and out of.
"""

from __future__ import annotations


def quality_gate(bars: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split bars into (clean, flagged). A flagged bar carries an ``issues`` list and is kept
    OUT of the clean set — never silently dropped, never silently fed forward."""
    clean: list[dict] = []
    flagged: list[dict] = []
    for b in bars:
        issues: list[str] = []
        for f in ("open", "high", "low", "close"):
            v = b.get(f)
            if v is None or v <= 0:
                issues.append(f"bad_{f}")
        hi, lo = b.get("high"), b.get("low")
        if hi is not None and lo is not None and hi < lo:
            issues.append("high_lt_low")
        if b.get("volume") is None or b.get("volume", 0) < 0:
            issues.append("bad_volume")
        if not b.get("symbol") or not b.get("date"):
            issues.append("missing_key")
        (flagged if issues else clean).append({**b, "issues": issues} if issues else b)
    return clean, flagged


def adjust_splits(bars: list[dict]) -> list[dict]:
    """Back-adjust prices for splits/dividends (§4.1). Synthetic data has no corporate actions,
    so this is identity in P0 — the seam exists so real adjustment lands behind it in P1."""
    return bars


def average_dollar_volume(bars: list[dict], symbol: str, window: int = 20) -> float:
    sb = sorted((b for b in bars if b["symbol"] == symbol), key=lambda x: x["date"])[-window:]
    if not sb:
        return 0.0
    return sum(b["close"] * b["volume"] for b in sb) / len(sb)


def liquidity_filter(bars: list[dict], drop_frac: float = 0.1,
                     window: int = 20) -> tuple[set[str], list[dict]]:
    """Drop the least-liquid ``drop_frac`` of symbols by average dollar volume. Returns
    (kept_symbols, dropped[{symbol, adv}]). Lenient in P0; thresholds are calibratable."""
    syms = sorted({b["symbol"] for b in bars})
    adv = sorted(((s, average_dollar_volume(bars, s, window)) for s in syms), key=lambda x: x[1])
    n_drop = int(len(adv) * drop_frac)
    dropped = [{"symbol": s, "adv": round(v, 1)} for s, v in adv[:n_drop]]
    kept = {s for s, _ in adv[n_drop:]}
    return kept, dropped
