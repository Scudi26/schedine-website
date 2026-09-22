"""The menu of picks the builder may use for a match, their fair chances, and how each one settles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .matrix import MarketView


@dataclass(frozen=True)
class PickType:
    code: str
    group: str
    wins: Callable[[int, int], bool]  # (home goals, away goals) -> did the pick win
    chance: Callable[[MarketView], float]


# Result, double chance and over/under 2.5 chances come straight from the market's own prices.
# Over 1.5, under 3.5 and both-teams-score come from the fitted score matrix.
PICKS: dict[str, PickType] = {p.code: p for p in [
    PickType("1", "result", lambda h, a: h > a, lambda v: v.p_home),
    PickType("X", "result", lambda h, a: h == a, lambda v: v.p_draw),
    PickType("2", "result", lambda h, a: h < a, lambda v: v.p_away),
    PickType("1X", "double chance", lambda h, a: h >= a, lambda v: v.p_home + v.p_draw),
    PickType("X2", "double chance", lambda h, a: h <= a, lambda v: v.p_away + v.p_draw),
    PickType("12", "double chance", lambda h, a: h != a, lambda v: v.p_home + v.p_away),
    PickType("O15", "goals", lambda h, a: h + a >= 2, lambda v: v.p_over15),
    PickType("O25", "goals", lambda h, a: h + a >= 3, lambda v: v.p_over25),
    PickType("U25", "goals", lambda h, a: h + a <= 2, lambda v: 1 - v.p_over25),
    PickType("U35", "goals", lambda h, a: h + a <= 3, lambda v: v.p_under35),
    PickType("GG", "both score", lambda h, a: h >= 1 and a >= 1, lambda v: min(0.99, v.p_btts + BTTS_SHIFT)),
    PickType("NG", "both score", lambda h, a: h == 0 or a == 0, lambda v: max(0.01, 1 - v.p_btts - BTTS_SHIFT)),
]}

# The independent-goals matrix underrates "both teams score". A flat +1.5 point shift, fitted on 2005-06 to
# 2016-17 and checked on 2017-18 to 2023-24 (tools/btts.py): GG promised 60.0% -> happened 60.7% in the slip
# band; NG still 58.2% -> 56.5%, so GG is offered and NG is not (its chance would be ~1.7 points too kind).
BTTS_SHIFT = 0.015
SLIP_MENU = frozenset(PICKS) - {"NG"}


@dataclass(frozen=True)
class Pick:
    match_id: str
    code: str
    chance: float  # fair chance that the pick wins
    odds: float    # the price the bookmaker offers


def settles(code: str, home_goals: int, away_goals: int) -> bool:
    return PICKS[code].wins(home_goals, away_goals)


def menu(match_id: str, view: MarketView, offered: dict[str, float], min_odds: float = 1.25,
         allowed: set[str] | None = None) -> list[Pick]:
    """Every usable pick for one match: offered by the bookmaker, allowed by the user, at or above the floor."""
    out = []
    allowed = SLIP_MENU if allowed is None else allowed
    for code, price in offered.items():
        if code not in PICKS:
            raise KeyError(f"unknown pick code {code!r}")
        if code not in allowed:
            continue
        if not price or price < min_odds:
            continue
        chance = PICKS[code].chance(view)
        if 0 < chance < 1:
            out.append(Pick(match_id, code, chance, float(price)))
    return out
