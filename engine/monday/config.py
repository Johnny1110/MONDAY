"""Monday engine configuration (P0).

The platform holds every data-source credential (TWSE/FinMind/CMoney/…) and the agents
hold only HTTP (invariants 1 & 2) — so this is where keys live, never in an agent prompt.
Everything else is small operational knobs (the PostgreSQL DSN, parquet data dir, webhook URL,
Telegram). Durable state = PostgreSQL (transactional) + parquet (large analysis tables), invariant 5.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- data-source credentials (held engine-side; never exposed to agents) -----
    # FinMind is the production primary (prices + 法人/margin chips + sector); the token lifts the
    # free-tier rate limit so a wide universe can backfill. TWSE/TPEx OpenAPI need no key.
    finmind_token: str = ""
    cmoney_user: str = ""
    cmoney_password: str = ""

    # --- outbound webhook (Monday engine -> evva swarm) --------------------------
    # POST {title, body, data, to}; token-free on the swarm side (invariant 8a).
    evva_webhook_url: str = "http://127.0.0.1:8888/api/swarm/monday/event"

    # --- Telegram (User-facing, invariant 8b) ------------------------------------
    # Both blank → disabled (no-op); keys stay engine-side (invariant 2).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- http server -------------------------------------------------------------
    monday_host: str = "127.0.0.1"
    monday_port: int = 7790

    # --- local state -------------------------------------------------------------
    # Transactional state — PostgreSQL (engine-internal; the DSN holds creds and lives here only,
    # never exposed to agents, invariant 2). Override via DATABASE_URL in .env.
    database_url: str = "postgresql://monday:monday@127.0.0.1:5432/monday"
    db_pool_min: int = 1                # psycopg connection-pool sizing
    db_pool_max: int = 10
    data_dir: str = "data"              # parquet root (PIT snapshots / prices / features)

    # --- strategy knobs (calibratable; start values per whitepaper §5) -----------
    max_recommendations: int = 20       # ≤20 daily ideas
    holding_window_days: int = 20       # ≤1-month swing window
    round_trip_cost_pct: float = 0.006  # honest fills (Imp): TW round-trip ≈ 0.1425%×2 broker + 0.3% tax + slippage
    candidate_pool: int = 50            # top-N the model hands to the LLM overlay
    drawdown_trigger_pct: float = 8.0   # portfolio_drawdown webhook threshold (hard, after the fact)
    drawdown_soft_pct: float = 4.0      # risk-gate graduated throttle: ease new exposure past this (Imp #3)
    calibration_min_samples: int = 30   # min settled outcomes before the conviction calibration map kicks in (else identity)
    calibration_ic_floor: float = 0.0   # §6.3: rank-IC below this for N runs → calibration_drift → quant-researcher
    calibration_drift_weeks: int = 3    # consecutive sub-floor calibration runs before firing drift
    factor_decay_periods: int = 3       # a factor's contribution <0 for N consecutive runs → factor_decay
    # exits (§5.5, Imp #2) — ATR-scaled TP/SL; fixed ±8% fallback when atr_14 is missing
    sl_atr_mult: float = 2.0            # stop distance = N×ATR …
    tp_atr_mult: float = 3.0           # take-profit distance ≥ N×ATR …
    tp_floor_pct: float = 0.08         # … but TP is at least this (and at least E[ret])
    sl_pct_floor: float = 0.04         # clamp ATR stop to [floor, cap] so it never gets silly
    sl_pct_cap: float = 0.15
    max_per_sector: int = 6             # risk gate: ≤N names per industry (§5.7); 6 = constitution's ≤30% of 20 (B17). Override via MAX_PER_SECTOR.
    liquidity_adv_floor: float = 0.0    # risk gate: min 20d avg dollar volume (0 = off; universe gate already filters)
    universe_size: int = 500            # real sources: top-N listed names by liquidity (§4.1; launch 500, widen to 800-1000)
    ingest_max_workers: int = 8         # concurrent FinMind fetches for the daily universe pull (politely bounds throughput)

    # --- 2.0 managed book (A1; the real/paper book the User trades) ---------------
    # invariant 11: the swarm NEVER places orders — fills land via the User's confirmation (A3). The
    # book stays `paper` until D1's dry-run gate passes, then the operator flips it to `real` (decision 3).
    book_mode: str = "paper"                  # paper | real
    book_starting_cash: float = 1_000_000.0   # NT$ notional, basis for sizing/exposure math (A4)
    book_max_position_pct: float = 20.0       # hard per-name cap as % of book (A4 sizing + risk gate read it)

    # --- 2.0 macro plane (A2; world indices for the top-down read) ----------------
    # Free, key-less Yahoo chart source (decision 6); PIT-snapshotted like prices. asset_class ∈
    # {equity_index, vol, fx, rate, commodity}. Override the whole map via MACRO_SYMBOLS (JSON) in .env.
    macro_source: str = "yahoo"
    macro_symbols: dict = {
        "^SOX":      {"name": "費城半導體",     "asset_class": "equity_index"},
        "^IXIC":     {"name": "那斯達克",       "asset_class": "equity_index"},
        "^GSPC":     {"name": "標普500",        "asset_class": "equity_index"},
        "^DJI":      {"name": "道瓊工業",       "asset_class": "equity_index"},
        "000001.SS": {"name": "上證指數",       "asset_class": "equity_index"},
        "^HSI":      {"name": "恒生指數",       "asset_class": "equity_index"},
        "^N225":     {"name": "日經225",        "asset_class": "equity_index"},
        "^STOXX50E": {"name": "歐洲STOXX50",    "asset_class": "equity_index"},
        "^VIX":      {"name": "VIX 波動率",     "asset_class": "vol"},
        "USDTWD=X":  {"name": "美元兌台幣",     "asset_class": "fx"},
        "^TNX":      {"name": "美10年期公債殖利率", "asset_class": "rate"},
        "GC=F":      {"name": "黃金期貨",       "asset_class": "commodity"},
        "CL=F":      {"name": "西德州原油期貨",  "asset_class": "commodity"},
    }


settings = Settings()


def reload() -> list[str]:
    """Re-read ``.env`` into the module-global ``settings`` IN PLACE (B4). The engine can be started
    before the deploy writes the FinMind token to ``.env``, and pydantic reads env only at construction;
    this lets an operator refresh config without a restart so existing ``from .config import settings``
    references see the new values. Returns the names of fields that changed — never their values
    (secrets stay engine-side, invariant 2)."""
    fresh = Settings()
    changed = []
    for name in Settings.model_fields:
        if getattr(settings, name) != getattr(fresh, name):
            changed.append(name)
        setattr(settings, name, getattr(fresh, name))
    return changed


def redacted_database_url() -> str:
    """``host:port/dbname`` of the transactional DB — for /status and logs WITHOUT the user:password
    (the DSN is engine-side; never leak creds to agents, invariant 2)."""
    from urllib.parse import urlsplit
    u = urlsplit(settings.database_url)
    port = f":{u.port}" if u.port else ""
    db = (u.path or "/").lstrip("/") or "?"
    return f"{u.hostname or '?'}{port}/{db}"
