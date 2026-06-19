"""/api/reports — User-facing notices (daily ideas / review summaries / alerts, invariant 8b).

The 1.0 generic feed (`GET/POST /api/reports`) is unchanged. 2.0 adds the structured **6-section daily
report** (A7): a computed scaffold morgan fills prose into, validated against the contract, persisted, and
pushed to the User (Telegram + dashboard) — always carrying the disclaimer (invariant 11).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import pagination, report as report_mod, store, telegram
from ..config import settings

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports(kind: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    return pagination.paginate(store.list_reports(kind), page, page_size)


@router.post("")
def add_report(payload: dict) -> dict:
    return store.add_report(payload.get("title", "(untitled)"), payload.get("body", ""),
                            payload.get("kind", "info"))


@router.get("/daily/scaffold")
def daily_scaffold(as_of: str | None = None) -> dict:
    """The engine-computed factual scaffold (A2/A3/A4/A5) morgan fills prose into (A7)."""
    return report_mod.build_scaffold(as_of)


@router.post("/daily")
def post_daily(payload: dict) -> dict:
    """Persist + push the composed 6-section report (A7). 422 if a section/disclaimer is missing. Stores
    the structured report, sets ``summary_text``, mirrors a line into the generic feed (back-compat), and
    fires Telegram (no-op if unset). The swarm composes prose; the User decides — engine never orders."""
    errs = report_mod.validate_report(payload)
    if errs:
        raise HTTPException(status_code=422, detail={"errors": errs})
    text = report_mod.render_text(payload)
    saved = store.add_daily_report({
        "as_of": payload["as_of"], "regime": payload.get("regime"),
        "risk_state": payload.get("risk_state"), "data": payload, "summary_text": text})
    store.add_report(f"每日報告 {payload['as_of']}", text, kind="recommendation")   # generic feed back-compat
    telegram.send(settings.telegram_bot_token, settings.telegram_chat_id,
                  telegram.format_daily_report(payload))                            # no-op when unset
    return saved


@router.get("/daily")
def get_daily(as_of: str | None = None) -> dict:
    """The latest structured 6-section report for ``as_of`` (default: the last pipeline day)."""
    day = as_of or store.kv_get("last_as_of")
    rep = store.get_daily_report(day) if day else None
    if not rep:
        return {"as_of": day, "report": None, "note": "no daily report yet — POST /api/reports/daily"}
    return rep
