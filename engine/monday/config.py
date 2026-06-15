"""Monday engine configuration (P0).

The platform holds every data-source credential (TWSE/FinMind/CMoney/…) and the agents
hold only HTTP (invariants 1 & 2) — so this is where keys live, never in an agent prompt.
Everything else is small operational knobs (sqlite path, parquet data dir, webhook URL,
Telegram). No Postgres/Redis: durable state is one sqlite file + parquet tables (invariant 5).
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
    sqlite_path: str = "monday.db"      # transactional state (recs/ledger/calibration/…)
    data_dir: str = "data"              # parquet root (PIT snapshots / prices / features)

    # --- strategy knobs (calibratable; start values per whitepaper §5) -----------
    max_recommendations: int = 20       # ≤20 daily ideas
    holding_window_days: int = 20       # ≤1-month swing window
    candidate_pool: int = 50            # top-N the model hands to the LLM overlay
    drawdown_trigger_pct: float = 8.0   # portfolio_drawdown webhook threshold
    max_per_sector: int = 5             # risk gate: ≤N names per industry (§5.7)
    liquidity_adv_floor: float = 0.0    # risk gate: min 20d avg dollar volume (0 = off; universe gate already filters)
    universe_size: int = 500            # real sources: top-N listed names by liquidity (§4.1; launch 500, widen to 800-1000)
    ingest_max_workers: int = 8         # concurrent FinMind fetches for the daily universe pull (politely bounds throughput)


settings = Settings()
