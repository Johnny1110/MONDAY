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
