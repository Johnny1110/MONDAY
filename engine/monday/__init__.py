"""Monday engine — the platform plane (invariant: deterministic, testable, holds keys).

A stateless TW-equity research platform that an evva swarm drives over token-free HTTP.
The full chain (ingest → clean → PIT snapshot → featurestore → model → write a recommendation →
mark-to-market) runs end to end on real free-core market data (FinMind primary, TWSE fallback),
and the pure-logic layers (pagination / calibration math / factors / mark-to-market) are
stdlib-testable. See ../../CLAUDE.md for the invariants and docs/whitepaper.md for the spec.
"""

__version__ = "0.0.1"
