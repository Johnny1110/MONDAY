"""Monday engine HTTP service — the platform plane (FastAPI, token-free).

Thin assembly layer: each API group lives under ``routers/`` (invariant 4 — prefixes by
module), durable state in ``store.py`` (sqlite) + parquet (``parquetio``). This file only wires
the routers, the system routes (``/health`` ``/manual`` ``/`` ``/dashboard``), and a boot probe
of the swarm webhook. Everything is token-free (invariants 2 & 4): the engine holds the keys.
"""

from __future__ import annotations

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, store
from .config import settings
from .routers import (admin, calibration, factors, features, journal, ledger, memory, models,
                      news, portfolio, prices, recommendations, reports, sentiment, signals,
                      system, universe)

log = logging.getLogger("monday")
_HERE = pathlib.Path(__file__).resolve().parent
_MANUAL = _HERE / "manual.md"
_WEB = _HERE / "web" / "dist"          # the built Vite dashboard; served at / and /ui
_INDEX = _WEB / "index.html"


async def _check_webhook_reachable() -> None:
    """Boot probe of the evva swarm webhook. Monday is event-driven (invariant 7) — if this URL
    is wrong or the swarm is down, agents silently never wake — so say it loudly at startup."""
    import asyncio

    from . import events
    if await asyncio.to_thread(events.probe, settings.evva_webhook_url):
        log.info("evva webhook reachable: %s", settings.evva_webhook_url)
    else:
        log.warning("evva webhook UNREACHABLE: %s — trigger events will be dropped (and logged) "
                    "until the swarm is up", settings.evva_webhook_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.connect(settings.sqlite_path)
    log.info("sqlite ready at %s; parquet data dir %s", settings.sqlite_path, settings.data_dir)
    await _check_webhook_reachable()
    yield
    store.close()


app = FastAPI(title="Monday engine", version=__version__, lifespan=lifespan)

for _r in (universe, prices, factors, features, models, signals, recommendations, portfolio,
           ledger, calibration, news, sentiment, memory, journal, reports, system, admin):
    app.include_router(_r.router)

# Serve the built dashboard's assets (Vite emits to web/dist with base=/ui/).
if _WEB.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB)), name="ui")


@app.get("/health")
def health() -> dict:
    """Liveness — dependency-free ping (no parquet read, no external call)."""
    return {"ok": True, "service": "monday-engine", "version": __version__}


@app.get("/manual", response_class=PlainTextResponse)
def manual() -> str:
    """The agent-facing API manual (the platform's contract; admin is intentionally omitted)."""
    return _MANUAL.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    """Serve the built Vite dashboard (web/dist/index.html); fall back to a placeholder until
    `npm run build` has produced dist/."""
    if _INDEX.is_file():
        return _INDEX.read_text(encoding="utf-8")
    last = store.kv_get("last_as_of") if store._conn is not None else None  # noqa: SLF001
    return ("<!doctype html><meta charset=utf-8><title>Monday</title>"
            "<body style='font-family:system-ui;background:#0b0e14;color:#cdd6f4;padding:3rem'>"
            "<h1>📈 Monday engine</h1>"
            "<p>API is live, but the dashboard isn't built. Run "
            "<code>npm install &amp;&amp; npm run build</code> in <code>engine/monday/web/</code>.</p>"
            f"<p>Last pipeline day: <code>{last or '—'}</code> · "
            "<a style='color:#89b4fa' href='/manual'>/manual</a></p>")
