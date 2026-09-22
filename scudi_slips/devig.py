"""Remove the bookmaker's margin from a set of prices.

Power method: find the exponent k such that sum((1/price)^k) = 1. It takes more margin out of
long prices than short ones, which matches how bookmakers load their margin, and it was the most
conservative well-calibrated method in our tests on Pinnacle's closing prices (decision 35).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def power_devig(prices: Sequence[float]) -> list[float]:
    """Fair probabilities (summing to 1) from the prices of all outcomes of one market."""
    if len(prices) < 2:
        raise ValueError("a market needs at least two outcomes")
    if any((not math.isfinite(p)) or p <= 1.0 for p in prices):
        raise ValueError(f"prices must be finite and greater than 1: {prices}")
    raw = [1.0 / p for p in prices]
    total = sum(raw)
    if total <= 1.0:  # no margin to remove (or an arbitrage): just normalise
        return [r / total for r in raw]
    lo, hi = 1.0, 50.0  # total > 1 at k=1 and falls towards 0 as k grows
    for _ in range(80):
        mid = (lo + hi) / 2
        if sum(r**mid for r in raw) > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    probs = [r**k for r in raw]
    s = sum(probs)
    return [p / s for p in probs]
