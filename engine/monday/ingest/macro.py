"""Macro adapter — world indices for the 2.0 top-down read (A2, whitepaper §4.3).

Free, **key-less** source: the Yahoo Finance v8 chart JSON (one GET per symbol), behind
``base.fetch_json`` so it inherits the platform's cache + per-host rate-limit + retry + quota
hygiene (invariant 6, stdlib urllib only). A single dead/blocked ticker is tolerated — it is
logged and omitted so one bad symbol never sinks the batch (the brief degrades, it doesn't crash).
The parser is pure (tested against a recorded fixture, no live network in tests).

**Benchmark fallback (ADR 0007)**: Yahoo rate-limits aggressively, and the home index / macro-call
benchmark (^TWII / TAIEX) is the one symbol the round cannot run without (GATE-1 data quality, A9
scoring). When Yahoo misses it, ``fetch_taiex`` serves it from TWSE — also key-less, a *different*
source family — so a Yahoo blackout degrades the global brief but never starves the round of the
benchmark. Only the benchmark has a TWSE equivalent; the global proxies stay Yahoo-best-effort plus
the macro-analyst's ``web_search`` overlay (PRD-002 decision 6).
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone

from . import base

log = logging.getLogger("monday.ingest")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo rejects a bare/unknown UA on some edges — present a browser-like one (no key, still token-free).
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _range_for(days: int) -> str:
    """Map a desired lookback to Yahoo's coarse ``range`` buckets — always wide enough for ≥2 bars
    (so prev_close exists across a weekend/holiday)."""
    if days <= 5:
        return "5d"
    if days <= 25:
        return "1mo"
    if days <= 80:
        return "3mo"
    return "6mo"


def parse_chart(payload: dict | None) -> list[dict]:
    """Yahoo v8 chart JSON → ``[{date, close}, …]`` ascending (latest last). Pure + tolerant: returns
    ``[]`` on any missing/malformed shape, skips null closes (the current incomplete bar). ``date`` is
    the **local trading date** (timestamp shifted by the exchange ``gmtoffset`` so an Asian midnight bar
    or a US 09:30 ET bar both land on the right civil day)."""
    try:
        result = (payload or {})["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return []
    timestamps = result.get("timestamp") or []
    try:
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []
    gmtoffset = (result.get("meta") or {}).get("gmtoffset") or 0
    rows = []
    for ts, c in zip(timestamps, closes):
        if ts is None or c is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts) + int(gmtoffset), tz=timezone.utc).date().isoformat()
            rows.append({"date": d, "close": float(c)})
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_indices(symbols: list[str], *, cache_dir: str | None = None, days: int = 7,
                  ttl: float = 43200) -> dict[str, list[dict]]:
    """Per symbol: GET the Yahoo chart via ``base.fetch_json`` (key-less, cached, rate-limited) and
    parse to ``[{date, close}, …]`` latest-last. Returns ``{symbol: rows}``, **omitting** any symbol
    that fails (dead ticker / malformed JSON / rate-limit) — a partial macro read is still useful and
    must never raise into the caller (invariant 8 spirit).

    Uses a shared cookie-jar opener so Yahoo treats the batch as one browser session instead of
    isolated bot requests (2026-06: Yahoo tightened anti-bot to require cookies even on the public
    v8 API; isolated requests hit 429 instantly)."""
    import http.cookiejar
    import urllib.request as _urllib
    from . import base as _base

    # Shared session with cookie support — one browser session for all symbols
    cj = http.cookiejar.CookieJar()
    opener = _urllib.build_opener(_urllib.HTTPCookieProcessor(cj))

    # Pre-warm: visit Yahoo's consent page so the session carries GUC/A1/A3 cookies before the
    # first chart call. Without cookies Yahoo treats every request as a cookieless bot and 429s
    # the very first attempt — even with a shared opener (2026-06).
    try:
        req = _urllib.Request("https://guce.yahoo.com/consent", headers={"User-Agent": _UA})
        opener.open(req, timeout=8)
    except Exception:
        pass  # best-effort — the opener is still useful even without pre-warmed cookies

    out: dict[str, list[dict]] = {}
    rng = _range_for(days)
    for sym in symbols:
        payload = None
        rate_hit = False
        for rate_retry in range(3):               # 2026-06: Yahoo rate-limits aggressively — retry with backoff
            try:
                payload = _base.fetch_json(
                    CHART_URL.format(symbol=urllib.parse.quote(sym)),
                    {"range": rng, "interval": "1d"},
                    cache_dir=cache_dir, ttl=ttl, rate_key="yahoo", min_interval=2.0,
                    headers={"User-Agent": _UA}, opener=opener)
                break                               # success — exit the rate-retry loop
            except _base.RateLimitError as e:
                rate_hit = True
                if rate_retry < 2:
                    import time as _time
                    wait = 5 * (rate_retry + 1)     # 5s, 10s backoff
                    log.debug("macro: %s 429 — pausing %d s before retry %d", sym, wait, rate_retry + 1)
                    _time.sleep(wait)
                    continue
                log.warning("macro: %s rate-limited after %d retries — omitted (%s)", sym, rate_retry, e)
                break
            except Exception as e:                  # noqa: BLE001 — one bad ticker never sinks the batch
                log.warning("macro: %s fetch failed — omitted (%s)", sym, e)
                break
        if payload is None:
            if not rate_hit:
                pass  # already logged in the exception handler
            continue
        rows = parse_chart(payload)
        if rows:
            out[sym] = rows
        else:
            log.warning("macro: %s returned no usable bars — omitted", sym)
    return out


# --- TWSE benchmark fallback (^TWII / TAIEX) ------------------------------------------
# TWSE publishes the TAIEX daily OHLC key-lessly as JSON (民國/ROC dates, thousands-separated closes).
# Used only when Yahoo can't serve the benchmark — see the module docstring (ADR 0007).

TAIEX_HIST_URL = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"


def _roc_to_iso(roc: str) -> str | None:
    """TWSE ROC date ``'YYY/MM/DD'`` (民國年) → ISO ``'YYYY-MM-DD'`` (ROC year + 1911). ``None`` on
    malformed input."""
    try:
        y, m, d = roc.strip().split("/")
        return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
    except (ValueError, AttributeError):
        return None


def parse_taiex_hist(payload: dict | None) -> list[dict]:
    """TWSE ``MI_5MINS_HIST`` JSON → ``[{date, close}, …]`` ascending (latest last). Pure + tolerant:
    ``[]`` on any missing/malformed shape, skips rows with an unparseable date/close. The close column
    (收盤指數) carries thousands separators (``'21,536.76'``) which are stripped."""
    rows = []
    for row in ((payload or {}).get("data") or []):
        try:
            iso = _roc_to_iso(row[0])
            close = float(str(row[4]).replace(",", ""))
        except (IndexError, ValueError, TypeError):
            continue
        if iso is not None:
            rows.append({"date": iso, "close": close})
    rows.sort(key=lambda r: r["date"])
    return rows


def _months_for(as_of: str | None) -> list[str]:
    """The two ``yyyymmdd`` month anchors to query (the as_of month + the prior month) so a prev_close
    survives a month boundary. ``as_of`` ``None`` → the current UTC month (engine code; only the
    Workflow sandbox forbids ``datetime.now``)."""
    if as_of:
        y, m = int(as_of[:4]), int(as_of[5:7])
    else:
        now = datetime.now(timezone.utc)
        y, m = now.year, now.month
    prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
    return [f"{y:04d}{m:02d}01", f"{prev_y:04d}{prev_m:02d}01"]


def fetch_taiex(as_of: str | None = None, *, cache_dir: str | None = None,
                ttl: float = 43200) -> list[dict]:
    """TAIEX (``^TWII``) daily closes from TWSE — the key-less fallback when Yahoo can't serve the home
    index. Queries the as_of month + the prior month (so prev_close survives a month boundary), merges
    and dedupes by date. Returns ``[{date, close}, …]`` latest-last, or ``[]`` if TWSE is unreachable
    too (never raises — the caller degrades)."""
    by_date: dict[str, float] = {}
    for anchor in _months_for(as_of):
        try:
            payload = base.fetch_json(
                TAIEX_HIST_URL, {"response": "json", "date": anchor},
                cache_dir=cache_dir, ttl=ttl, rate_key="twse", min_interval=0.6)
        except base.RateLimitError as e:
            log.warning("macro fallback: TAIEX %s rate-limited — skipped (%s)", anchor, e)
            continue
        except Exception as e:                      # noqa: BLE001 — the fallback must never raise
            log.warning("macro fallback: TAIEX %s fetch failed — skipped (%s)", anchor, e)
            continue
        for bar in parse_taiex_hist(payload):
            by_date[bar["date"]] = bar["close"]
    return [{"date": d, "close": by_date[d]} for d in sorted(by_date)]
