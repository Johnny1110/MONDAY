"""Outbound webhook events: Monday engine → evva swarm (invariant 8a).

PURE + stdlib (urllib, no httpx): builders assemble the ``{title, body, data, to}`` payload
the swarm webapi expects; ``post`` fires it and NEVER raises (the engine must keep serving
even when the swarm is down). Each event is **self-sufficient** — it carries the structured
numbers plus a ``suggested_action`` so a woken agent can act on its first turn without a
round-trip. The four P0 event kinds map to the whitepaper §6.3 triggers.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("monday.events")


def build_event(title: str, body: str, data: dict | None = None, to: str = "leader") -> dict:
    """Assemble the swarm webhook payload: {title, body, data, to}."""
    return {"title": title, "body": body, "data": data or {}, "to": to}


def portfolio_drawdown_event(drawdown_pct: float, threshold_pct: float,
                             to: str = "leader") -> dict:
    """`portfolio_drawdown`: paper portfolio retraced past the risk line (§6.3)."""
    return build_event(
        f"portfolio drawdown {drawdown_pct:.1f}% > {threshold_pct:.0f}%",
        f"紙上投組回撤 {drawdown_pct:.1f}%（門檻 {threshold_pct:.0f}%）。",
        data={"event_type": "portfolio_drawdown",
              "drawdown_pct": round(drawdown_pct, 2), "threshold_pct": threshold_pct,
              "suggested_action": "緊急復盤：降曝險/暫停新建議直到診斷（GET /api/portfolio, /api/ledger）。"},
        to=to)


def calibration_drift_event(ic: float, weeks: int, to: str = "quant-researcher") -> dict:
    """`calibration_drift`: predicted-vs-realized IC below floor for N weeks (§6.3)."""
    return build_event(
        f"calibration drift: IC {ic:+.2f} for {weeks}w",
        f"預測 vs 實際 IC 連 {weeks} 週低於門檻（現值 {ic:+.2f}）。",
        data={"event_type": "calibration_drift", "ic": round(ic, 3), "weeks": weeks,
              "suggested_action": "強制提前重訓、查資料/regime 是否變了（GET /api/calibration）。"},
        to=to)


def factor_decay_event(factor: str, ic: float, periods: int,
                       to: str = "quant-researcher") -> dict:
    """`factor_decay`: a factor's IC has turned negative for N periods (§6.3)."""
    return build_event(
        f"factor decay: {factor} IC {ic:+.2f}",
        f"因子 {factor} IC 連 {periods} 期翻負（現值 {ic:+.2f}）。",
        data={"event_type": "factor_decay", "factor": factor, "ic": round(ic, 3),
              "periods": periods,
              "suggested_action": f"評估 {factor} 降權/退役提案，記 ADR。"},
        to=to)


def pipeline_failed_event(stage: str, detail: str, to: str = "leader") -> dict:
    """`pipeline_failed`: an ingest/feature/inference stage failed (§6.3)."""
    return build_event(
        f"pipeline failed at {stage}",
        f"pipeline 在 {stage} 階段失敗：{detail}",
        data={"event_type": "pipeline_failed", "stage": stage, "detail": detail,
              "suggested_action": "修復；必要時當日不發建議（誠實 > 硬發）。"},
        to=to)


def pipeline_complete_event(as_of: str, candidate_count: int, signals_version: str | None = None,
                            regime: str | None = None, degraded_factors: list | None = None,
                            to: str = "leader") -> dict:
    """`pipeline_complete`: the daily chain finished and signals are refreshed — wake downstream agents
    event-driven instead of on a fixed cron (B12). Carries the signals_version so a woken agent acts on
    exactly the snapshot just produced (no race with a later run)."""
    degraded = degraded_factors or []
    warn = f"；退化因子 {degraded}（歷史深度不足）" if degraded else ""
    return build_event(
        f"pipeline complete: {as_of} ({candidate_count} candidates)",
        f"當日 pipeline 完成，{as_of} 訊號已更新（{candidate_count} 檔候選，regime={regime}）{warn}。",
        data={"event_type": "pipeline_complete", "as_of": as_of,
              "candidate_count": candidate_count, "signals_version": signals_version,
              "regime": regime, "degraded_factors": degraded,
              "suggested_action": "對候選集做分析師 overlay／風險閘（GET /api/signals/today, /api/portfolio/risk），"
                                  "再 POST /api/recommendations/finalize 定案。"},
        to=to)


def macro_drift_event(hit_rate: float, periods: int, to: str = "morgan") -> dict:
    """`macro_drift` (A9): the macro-call hit-rate has been below floor for N reviews — the top-down
    framework may be systematically biased. Wakes morgan/macro-analyst to recalibrate the 定調 process."""
    return build_event(
        f"macro drift: hit-rate {hit_rate:.0%} for {periods} reviews",
        f"宏觀判斷命中率連 {periods} 次低於門檻（現值 {hit_rate:.0%}）。",
        data={"event_type": "macro_drift", "hit_rate": round(hit_rate, 3), "periods": periods,
              "suggested_action": "復盤宏觀框架：是否系統性偏多/偏空？校正定調流程（GET /api/calibration/macro）。"},
        to=to)


def regime_shift_event(ic: float, corr: float, to: str = "reviewer-calibrator") -> dict:
    """`regime_shift`: calibration IC dipped but the drop correlates with benchmark return
    (|corr| > 0.7) — this is a market regime change, not model degradation. The drift alert is
    suppressed; this softer event records the observation for the Friday review (task #101)."""
    return build_event(
        f"regime shift suspected: IC {ic:+.2f}, |corr(IC,benchmark)|={abs(corr):.2f}",
        f"IC 降至 {ic:+.2f} 但與大盤報酬高度相關（|r|={abs(corr):.2f}>0.7），"
        f"推測為 regime shift 而非模型退化。保持觀察，不強制重訓。",
        data={"event_type": "regime_shift", "ic": round(ic, 3),
              "benchmark_corr": round(corr, 3),
              "suggested_action": "週五複盤確認 regime；若持續則記 ADR 並調整校準 baseline。"},
        to=to)


def round_requested_event(as_of: str, requested_by: str = "user", to: str = "morgan") -> dict:
    """`round_requested`: the User manually woke Monday for today's round (A8, §workflow 啟動時機). Wakes
    the leader to run the manual-round SOP (B3) — it does NOT run the pipeline itself (morgan
    task_assigns data-engineer for that)."""
    return build_event(
        f"round_requested: {as_of}",
        f"User 要求啟動今日 round（{as_of}）。執行手動 round SOP："
        f"定調 → 聚焦板塊 → quant rescope → 分析師 overlay → 風控閘 → 定案 → 六段報告。",
        data={"event_type": "round_requested", "as_of": as_of, "requested_by": requested_by,
              "suggested_action": "run_daily_round"},
        to=to)


def _build_request(url: str, payload: dict) -> urllib.request.Request:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    return req


def post(url: str, payload: dict, timeout: float = 3.0) -> tuple[int | None, bool]:
    """Fire-and-forget POST. Returns (http_status, ok); never raises (invariant 8). A dropped
    event means a sleeping agent that never wakes, so every failure path logs here."""
    title = payload.get("title", "?")
    if not url or not url.strip():
        log.warning("webhook dropped (EVVA_WEBHOOK_URL empty): %s", title)
        return None, False
    try:
        with urllib.request.urlopen(_build_request(url, payload), timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return status, True
    except urllib.error.HTTPError as e:
        log.warning("webhook POST %s rejected (HTTP %s): %s", url, e.code, title)
        return e.code, False
    except Exception as e:
        log.warning("webhook POST %s failed (%s): %s", url, e, title)
        return None, False


def probe(url: str, timeout: float = 3.0) -> bool:
    """Boot-time reachability check: GET the swarm origin's /healthz. Never raises."""
    if not url or not url.strip():
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        with urllib.request.urlopen(f"{parts.scheme}://{parts.netloc}/healthz", timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return 200 <= status < 300
    except Exception:
        return False
