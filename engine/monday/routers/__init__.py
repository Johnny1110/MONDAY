"""HTTP routers — one module per API prefix (invariant 4).

Every router is token-free (invariants 2 & 4): the platform holds the keys, the agent holds
only HTTP. List endpoints return the uniform pagination envelope (invariant 3). admin is
operator-only and is NOT advertised to agents in /manual.
"""
