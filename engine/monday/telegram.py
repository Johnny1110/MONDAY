"""User-facing Telegram push (invariant 8b).

The SECOND outbound channel (the evva webhook is agent-facing): daily ideas / review
summaries / major alerts to the User's phone. PURE stdlib (urllib). If either credential is
unset it is a **no-op** — the engine behaves exactly as before — so dev/CI never needs keys.
Keys stay engine-side (invariant 2) and delivery is fire-and-forget, never raising (invariant 8).
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("monday.telegram")


def enabled(token: str, chat_id: str) -> bool:
    return bool(token and token.strip() and chat_id and chat_id.strip())


def send(token: str, chat_id: str, text: str, timeout: float = 4.0) -> bool:
    """Send a Markdown message. No-op (returns False) when unconfigured; never raises."""
    if not enabled(token, chat_id):
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
               "disable_web_page_preview": True}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= (getattr(resp, "status", None) or resp.getcode()) < 300
    except Exception as e:
        log.warning("telegram send failed (%s)", e)
        return False


def format_daily_report(report: dict) -> str:
    """Concise phone render of the 6-section daily report (A7) — macro → stance → holdings actions →
    top new ideas (TP/SL/size) → exposure → risk, ending with the mandatory disclaimer (invariant 11)."""
    s = report.get("sections", {})
    lines = [f"*Monday — {report.get('as_of', '?')}*  "
             f"(regime {report.get('regime', '?')}, risk {report.get('risk_state', '?')})"]

    macro = s.get("macro", {})
    if macro.get("read"):
        lines.append(f"🌏 {macro['read']}")
    mn = s.get("market_narrative", {})
    stance = mn.get("stance") or mn.get("read")
    if stance:
        lines.append(f"🎯 {stance}")
    if mn.get("hot_sectors"):
        lines.append(f"聚焦：{', '.join(mn['hot_sectors'])}")

    hr = s.get("holdings_review") or []
    if hr:
        lines.append("*持倉*：" + "；".join(
            f"{h.get('symbol')} {str(h.get('action', '')).upper()} ({h.get('mtm_pct')}%)" for h in hr))

    ni = s.get("new_ideas") or []
    if ni:
        lines.append("*新標的*：")
        for n in ni[:10]:
            lines.append(f"• `{n.get('symbol')}` {n.get('name', '')} {n.get('entry_ref')}→"
                         f"TP {n.get('take_profit')}/SL {n.get('stop_loss')} "
                         f"{n.get('suggested_pct')}% (conv {n.get('conviction')})")
    else:
        lines.append("今日不發新標的。")

    ex = s.get("exposure", {})
    lines.append(f"曝險 {ex.get('net_pct')}% / 現金 {ex.get('cash_pct')}%")
    rn = s.get("risk_notes", {})
    if rn.get("invalidation"):
        lines.append(f"⚠️ {rn['invalidation']}")
    lines.append(f"_{report.get('disclaimer', '')}_")
    return "\n".join(lines)


def format_recommendations(envelope: dict) -> str:
    """Render the daily recommendation envelope (whitepaper appendix C) as a phone message."""
    recs = envelope.get("recommendations", [])
    head = (f"*Monday — {envelope.get('as_of_date','?')}*  "
            f"(model `{envelope.get('model_version','?')}`, regime {envelope.get('regime','?')})\n"
            f"{len(recs)} ideas:")
    lines = [head]
    for r in recs[:20]:
        lines.append(
            f"• `{r.get('symbol')}` {r.get('name','')} {r.get('direction','long')} "
            f"entry {r.get('entry_ref')} → TP {r.get('take_profit')} / SL {r.get('stop_loss')} "
            f"(conv {r.get('conviction')})")
    return "\n".join(lines)
