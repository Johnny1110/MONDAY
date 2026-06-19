"""Daily report v2 (A7, §完整 workflow 六段報告) — build the factual scaffold, validate, render.

The User's deliverable is a structured 6-section report: 宏觀定調 / 台股盤勢與新敘事 / 持倉檢視 /
今日新標的 / 倉位與曝險 / 風險提醒. The QUANTITATIVE facts are engine-computable (macro numbers, holdings
MTM + mechanical review action, new-idea sizing/TP/SL, exposure); the PROSE (macro read, narrative,
rationale, invalidation) is morgan/analyst judgement. ``build_scaffold`` computes the facts with prose
blank; ``validate_report`` enforces the contract; ``render_text`` produces ``summary_text``. Every report
carries the disclaimer (invariant 11 — the swarm never places orders).
"""

from __future__ import annotations

import datetime as _dt

DISCLAIMER = "研究意見，下單與盈虧 User 自負（swarm 不下單）。"
SECTIONS = ("macro", "market_narrative", "holdings_review", "new_ideas", "exposure", "risk_notes")


def _days(opened_at: str | None, as_of: str | None) -> int:
    try:
        return (_dt.date.fromisoformat(as_of) - _dt.date.fromisoformat(opened_at)).days
    except (ValueError, TypeError):
        return 0


def build_scaffold(as_of: str | None = None) -> dict:
    """The engine-computed factual shell morgan fills prose into (A2/A3/A4/A5). Prose fields are blank.
    Populated even on a no-new-ideas day (holdings_review + macro still present)."""
    import json

    from . import book as book_mod
    from . import exits
    from . import macro as macro_mod
    from . import review as review_mod
    from . import sizing as sizing_mod
    from . import store
    from .config import settings

    as_of = as_of or store.kv_get("last_as_of") or _dt.date.today().isoformat()
    book_name = settings.book_mode

    # --- 宏觀定調 (A2) ---
    overnight = [{"symbol": r["symbol"], "name": r.get("name"), "chg_pct": r.get("chg_pct"),
                  "asset_class": r.get("asset_class")}
                 for r in macro_mod.read_macro_snapshot(settings.data_dir, None)]

    # --- 倉位與曝險 (A3) ---
    exp = book_mod.book_exposure(book_name)
    total = exp.get("total") or settings.book_starting_cash

    def _pct(v):
        return round((v or 0.0) / total * 100, 1) if total else 0.0

    exposure = {"gross_pct": _pct(exp.get("gross")), "net_pct": _pct(exp.get("net")),
                "cash_pct": _pct(exp.get("cash")),
                "by_sector": {k: _pct(v) for k, v in (exp.get("by_sector") or {}).items()},
                "target_exposure_pct": None}

    # --- 持倉檢視 (A5, mechanical baseline) ---
    prices = book_mod._latest_prices()                          # noqa: SLF001 — shared PIT price helper
    cfg = {"holding_window_days": settings.holding_window_days,
           "review_trim_profit_pct": settings.review_trim_profit_pct,
           "review_add_conviction": settings.review_add_conviction,
           "review_trail_to_be_pct": settings.review_trail_to_be_pct}
    holdings_review = []
    for p in book_mod.list_book(book_name, "open"):
        price = prices.get(p["symbol"])
        rv = review_mod.review_position({**p, "days_held": _days(p.get("opened_at"), as_of),
                                         "holding_window": settings.holding_window_days},
                                        {"price": price}, cfg)
        mtm = round((price / p["avg_entry"] - 1) * 100, 2) if (price and p.get("avg_entry")) else None
        holdings_review.append({
            "symbol": p["symbol"], "name": p.get("name"), "qty": p.get("qty"),
            "avg_entry": p.get("avg_entry"), "price": price, "mtm_pct": mtm,
            "action": rv["action"], "reason": "",
            "updated_tp": rv["updated_tp"], "updated_sl": rv["updated_sl"]})

    # --- 今日新標的 (A4, sized; prose blank) ---
    env = json.loads(store.kv_get("signals_today") or "{}")
    regime = env.get("regime")
    new_ideas = []
    for cd in (env.get("candidates") or [])[:settings.max_recommendations]:
        if cd.get("held"):                                     # held names live in holdings_review, not "new"
            continue
        entry = cd.get("close")
        atr14 = (cd.get("factors") or {}).get("atr_14")
        tp, sl, _basis = exits.tp_sl_prices(
            entry, cd.get("predicted_return"), atr14, "long",
            sl_atr_mult=settings.sl_atr_mult, tp_atr_mult=settings.tp_atr_mult,
            tp_floor_pct=settings.tp_floor_pct, sl_pct_floor=settings.sl_pct_floor,
            sl_pct_cap=settings.sl_pct_cap)
        sz = sizing_mod.suggest_size(
            cd.get("conviction"), sizing_mod.stop_pct(None, sl, entry, settings.sl_pct_floor),
            risk_budget_pct=settings.risk_budget_pct_per_trade, regime_state=regime or "neutral",
            max_position_pct=settings.book_max_position_pct, book_value=total, price=entry,
            lot_size=settings.lot_size)
        new_ideas.append({
            "symbol": cd["symbol"], "name": cd.get("name"), "direction": "long",
            "entry_ref": entry, "take_profit": tp, "stop_loss": sl,
            "suggested_pct": sz["suggested_pct"], "suggested_qty": sz["suggested_qty"],
            "conviction": cd.get("conviction"), "sector": cd.get("sector"),
            "rationale": "", "risk_notes": ""})

    return {
        "as_of": as_of, "regime": regime, "risk_state": None,
        "sections": {
            "macro": {"risk_state": None, "overnight": overnight, "read": ""},
            "market_narrative": {"regime": regime, "hot_sectors": env.get("focus_sectors", []),
                                 "new_narratives": [], "stance": "", "read": ""},
            "holdings_review": holdings_review,
            "new_ideas": new_ideas,
            "exposure": exposure,
            "risk_notes": {"events": [], "landmines": [], "invalidation": ""},
        },
        "disclaimer": DISCLAIMER,
    }


def validate_report(payload: dict) -> list[str]:
    """[] when valid; otherwise messages naming the missing/mistyped pieces (POST returns 422 with them).
    The disclaimer is mandatory (invariant 11)."""
    if not isinstance(payload, dict):
        return ["report must be an object"]
    errs = []
    if not payload.get("as_of"):
        errs.append("missing as_of")
    if not payload.get("disclaimer"):
        errs.append("missing disclaimer")
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return errs + ["missing sections"]
    for s in SECTIONS:
        if s not in sections:
            errs.append(f"missing section: {s}")
    for list_section in ("holdings_review", "new_ideas"):
        if list_section in sections and not isinstance(sections[list_section], list):
            errs.append(f"{list_section} must be a list")
    return errs


def render_text(report: dict) -> str:
    """Plain-text/markdown summary for ``daily_report.summary_text`` + the dashboard fallback."""
    s = report.get("sections", {})
    out = [f"# Monday 每日報告 — {report.get('as_of', '?')} "
           f"(regime={report.get('regime', '?')}, risk={report.get('risk_state', '?')})"]

    macro = s.get("macro", {})
    out.append("\n## 宏觀定調")
    if macro.get("read"):
        out.append(macro["read"])
    ov = ", ".join(f"{o.get('name') or o.get('symbol')} {o.get('chg_pct')}%"
                   for o in (macro.get("overnight") or [])[:6])
    if ov:
        out.append(f"隔夜：{ov}")

    mn = s.get("market_narrative", {})
    out.append("\n## 台股盤勢與新敘事")
    if mn.get("read"):
        out.append(mn["read"])
    if mn.get("hot_sectors"):
        out.append(f"聚焦板塊：{', '.join(mn['hot_sectors'])}")
    if mn.get("new_narratives"):
        out.append(f"新敘事：{', '.join(mn['new_narratives'])}")

    out.append("\n## 持倉檢視")
    hr = s.get("holdings_review") or []
    if not hr:
        out.append("（無持倉）")
    for h in hr:
        out.append(f"- {h.get('symbol')} {h.get('name') or ''} {str(h.get('action', '')).upper()} "
                   f"MTM {h.get('mtm_pct')}%" + (f" — {h['reason']}" if h.get("reason") else ""))

    out.append("\n## 今日新標的")
    ni = s.get("new_ideas") or []
    if not ni:
        out.append("今日不發新標的。")
    for n in ni:
        out.append(f"- {n.get('symbol')} {n.get('name') or ''} entry {n.get('entry_ref')} "
                   f"TP {n.get('take_profit')} / SL {n.get('stop_loss')} "
                   f"size {n.get('suggested_pct')}% (conv {n.get('conviction')})"
                   + (f" — {n['rationale']}" if n.get("rationale") else ""))

    ex = s.get("exposure", {})
    out.append("\n## 倉位與曝險")
    tgt = f"（目標 {ex.get('target_exposure_pct')}%）" if ex.get("target_exposure_pct") is not None else ""
    out.append(f"曝險 {ex.get('net_pct')}% / 現金 {ex.get('cash_pct')}%{tgt}")
    if ex.get("by_sector"):
        out.append("產業：" + ", ".join(f"{k} {v}%" for k, v in ex["by_sector"].items()))

    rn = s.get("risk_notes", {})
    out.append("\n## 風險提醒")
    if rn.get("events"):
        out.append("事件：" + ", ".join(rn["events"]))
    if rn.get("landmines"):
        out.append("地雷：" + ", ".join(rn["landmines"]))
    if rn.get("invalidation"):
        out.append(f"反向情境：{rn['invalidation']}")

    out.append(f"\n— {report.get('disclaimer', DISCLAIMER)}")
    return "\n".join(out)
