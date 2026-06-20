"""HTTP fetch for ingest adapters — retry + rate-limit + on-disk cache (whitepaper §2 platform).

Lazy stdlib urllib (invariant 6) — no third-party HTTP client. The platform owns scraping
hygiene so adapters stay thin:
  * a per-host **minimum interval** between calls (politeness to the free sources),
  * a few **retries** with linear backoff on transient errors,
  * a TTL'd **JSON cache** on disk so re-pulling the same day doesn't re-hit the source (and a
    warmed dev run is reproducible offline).
``cache_dir`` is passed in (adapters get it from config), keeping this module config-free.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("monday.ingest")

_last_call: dict[str, float] = {}   # rate_key → last wall-clock call time
_rate_lock = threading.Lock()       # guards _last_call for concurrent fetches

# Source usage counters (B3b) — per rate_key {calls, rate_limited, last_call_at, last_rate_limited_at}.
# Counts only real network requests (cache hits return before the request loop), so it reflects FinMind
# quota consumption. Drained by the pipeline at run-end into a per-day KV tally (GET /api/system/quota).
_quota: dict[str, dict] = {}
_quota_lock = threading.Lock()


def _quota_bump(rate_key: str | None, *, rate_limited: bool = False) -> None:
    if not rate_key:
        return
    iso = datetime.now(timezone.utc).isoformat()
    with _quota_lock:
        q = _quota.setdefault(rate_key, {"calls": 0, "rate_limited": 0,
                                         "last_call_at": None, "last_rate_limited_at": None})
        if rate_limited:
            q["rate_limited"] += 1
            q["last_rate_limited_at"] = iso
        else:
            q["calls"] += 1
            q["last_call_at"] = iso


def quota_snapshot() -> dict:
    """A copy of the live per-source counters (does not reset)."""
    with _quota_lock:
        return {k: dict(v) for k, v in _quota.items()}


def reset_quota_counters() -> dict:
    """Return the current counters AND zero them — the pipeline drains these into the daily KV tally."""
    with _quota_lock:
        snap = {k: dict(v) for k, v in _quota.items()}
        _quota.clear()
        return snap


class RateLimitError(RuntimeError):
    """Raised on HTTP 402/429 (source quota hit) — retrying in-run won't help, so callers
    should stop and degrade gracefully (e.g. proceed with the partial universe)."""


def _cache_path(cache_dir: str, url: str, params: dict | None) -> pathlib.Path:
    raw = url + "?" + urllib.parse.urlencode(sorted((params or {}).items()))
    return pathlib.Path(cache_dir) / f"{hashlib.sha1(raw.encode()).hexdigest()}.json"


def _read_cache(path: pathlib.Path, ttl: float):
    if not path.is_file():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return blob.get("data") if time.time() - blob.get("ts", 0) <= ttl else None


def _write_cache(path: pathlib.Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError as e:
        log.warning("ingest cache write failed: %s", e)


def _rate_limit(rate_key: str | None, min_interval: float) -> None:
    # Thread-safe global spacing per rate_key. Concurrent callers pass min_interval=0 and bound
    # throughput via their thread-pool size instead (the per-call serial wait is the bottleneck
    # that made a full-universe pull take >15 min).
    if not rate_key or min_interval <= 0:
        return
    with _rate_lock:
        wait = min_interval - (time.time() - _last_call.get(rate_key, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[rate_key] = time.time()


def fetch_json(url: str, params: dict | None = None, *, cache_dir: str | None = None,
               ttl: float = 86400, rate_key: str | None = None, min_interval: float = 0.6,
               retries: int = 3, timeout: float = 20, headers: dict | None = None):
    """GET JSON with cache → rate-limit → retry. Returns parsed JSON; raises after ``retries``."""
    cache_file = _cache_path(cache_dir, url, params) if cache_dir else None
    if cache_file is not None:
        cached = _read_cache(cache_file, ttl)
        if cached is not None:
            return cached

    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers=headers or {"User-Agent": "monday-engine/0.0.1"})
    err = None
    ssl_fallback = False                          # BUG-022: TPEx SSL fails on Python 3.14 / macOS
    for attempt in range(retries):
        _rate_limit(rate_key, min_interval)
        _quota_bump(rate_key)                    # a real request is about to leave (cache hits never reach here)
        try:
            # Normal SSL context; on the second+ attempt and after an SSL error, fall back to
            # unverified context (TPEx TLS certificates may lack a Subject Key Identifier).
            ctx = None
            if ssl_fallback:
                import ssl as _ssl
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
            kwargs = {"timeout": timeout}
            if ssl_fallback:
                kwargs["context"] = ctx
            with urllib.request.urlopen(req, **kwargs) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if cache_file is not None:
                _write_cache(cache_file, data)
            if ssl_fallback:
                log.info("ingest fetch %s succeeded with SSL fallback", url)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (402, 429):             # source quota / rate limit — in-run retry is futile
                _quota_bump(rate_key, rate_limited=True)
                raise RateLimitError(f"{url}: HTTP {e.code} (rate limit / quota)") from e
            err = e
            log.warning("ingest fetch %s failed (attempt %d/%d): %s", url, attempt + 1, retries, e)
            time.sleep(0.8 * (attempt + 1))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
            err = e
            # URLError wrapping an SSLError → enable fallback for remaining attempts
            if isinstance(e, urllib.error.URLError) and hasattr(e, "reason"):
                reason = e.reason
                if isinstance(reason, Exception) and "SSL" in type(reason).__name__:
                    ssl_fallback = True
                    log.warning("ingest SSL error — will retry with fallback: %s", e)
            log.warning("ingest fetch %s failed (attempt %d/%d): %s", url, attempt + 1, retries, e)
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"ingest fetch failed after {retries} attempts: {url}: {err}")
