"""Accumulator bonus rules.

SNAI "Bonus Multipla" as reported by betscanner.it and assopoker.com in September 2026 (not yet
checked on snai.it itself): from 5 to 30 events, each event priced 1.25 or more, the winnings grow
by 3.5% compounded for every event from the fifth: 5 -> 3.50%, 9 -> 18.77%, 10 -> 22.93%,
20 -> 73.40%, 30 -> 144.60%. Events under 1.25 do not count. Antepost and system bets get nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

SNAI_MIN_ODDS = 1.25
SNAI_MIN_EVENTS = 5
SNAI_MAX_EVENTS = 30
SNAI_STEP = 1.035


def snai_bonus(leg_odds: Iterable[float]) -> float:
    """Bonus as a fraction of the winnings (0.2293 = +22.93%) for a slip with these leg prices."""
    qualifying = sum(1 for o in leg_odds if o >= SNAI_MIN_ODDS)
    if qualifying < SNAI_MIN_EVENTS:
        return 0.0
    return SNAI_STEP ** (min(qualifying, SNAI_MAX_EVENTS) - (SNAI_MIN_EVENTS - 1)) - 1.0
