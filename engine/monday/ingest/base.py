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
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("monday.ingest")

_last_call: dict[str, float] = {}   # rate_key → last wall-clock call time


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
    if not rate_key:
        return
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
    for attempt in range(retries):
        _rate_limit(rate_key, min_interval)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if cache_file is not None:
                _write_cache(cache_file, data)
            return data
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
            err = e
            log.warning("ingest fetch %s failed (attempt %d/%d): %s", url, attempt + 1, retries, e)
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"ingest fetch failed after {retries} attempts: {url}: {err}")
