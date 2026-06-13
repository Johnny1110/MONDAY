"""Feature store: per-symbol-per-day factors computed post-close (whitepaper §4.3).

``factors`` is pure stdlib (unit-testable anywhere, invariant 6); ``build`` assembles the daily
feature rows and persists them to parquet (invariant 5). P0 ships the momentum/technical group;
flow / fundamentals / event / sentiment / regime groups land in P1.
"""
