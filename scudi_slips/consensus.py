"""One fair view of a match from several bookmakers' prices.

Each bookmaker's market is de-vigged on its own (power method), then the fair probabilities are
averaged with weights: sharp books count more. Pinnacle and the Betfair exchange are the sharpest
public prices (they were the best-calibrated reference in decisions 31-35); an ordinary book gets
weight 1. A market from a single book is used as it is. Books whose prices look stale (older than
`max_age_hours` at pull time) or inconsistent (margin outside 0-15%) are dropped first.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .devig import power_devig

SHARP_WEIGHTS: dict[str, float] = {"pinnacle": 3.0, "betfair_ex_eu": 2.0, "betfair_ex_uk": 2.0, "betfair_ex_au": 2.0, "matchbook": 1.5}
MAX_MARGIN = 0.15


@dataclass
class BookMarket:
    book: str
    prices: list[float]           # one price per outcome, in a fixed outcome order
    updated: datetime | None = None
    weight: float = field(default=None)  # filled from SHARP_WEIGHTS when None

    def __post_init__(self):
        if self.weight is None:
            self.weight = SHARP_WEIGHTS.get(self.book, 1.0)


@dataclass(frozen=True)
class Consensus:
    probs: tuple[float, ...]
    books_used: int
    books_dropped: int
    sharp_share: float            # share of the total weight that came from sharp books


def usable(m: BookMarket, now: datetime | None, max_age: timedelta) -> bool:
    """Fresh, consistent and really a market: the same test the consensus applies."""
    if any(p <= 1.0 for p in m.prices):
        return False
    margin = sum(1.0 / p for p in m.prices) - 1.0
    if not (0.0 <= margin <= MAX_MARGIN):
        return False
    if now is not None and m.updated is not None and now - m.updated > max_age:
        return False
    return True


def consensus(markets: Iterable[BookMarket], now: datetime | None = None, max_age_hours: float = 48.0) -> Consensus | None:
    """Weighted average of the de-vigged probabilities of every usable book. None when no book is usable."""
    max_age = timedelta(hours=max_age_hours)
    good, dropped = [], 0
    for m in markets:
        if usable(m, now, max_age):
            good.append(m)
        else:
            dropped += 1
    if not good:
        return None
    n = len(good[0].prices)
    if any(len(m.prices) != n for m in good):
        raise ValueError("every book must price the same outcomes")
    total_w = sum(m.weight for m in good)
    acc = [0.0] * n
    for m in good:
        fair = power_devig(m.prices)
        for i in range(n):
            acc[i] += m.weight * fair[i]
    probs = tuple(a / total_w for a in acc)
    sharp = sum(m.weight for m in good if m.book in SHARP_WEIGHTS) / total_w
    return Consensus(probs, len(good), dropped, sharp)


def best_price(offers: Mapping[str, float]) -> tuple[str, float] | None:
    """The highest price on one outcome across books (for the 'what would it pay elsewhere' view)."""
    if not offers:
        return None
    book = max(offers, key=lambda k: offers[k])
    return book, offers[book]
