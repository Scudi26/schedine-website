"""The menu of picks the builder may use for a match, their fair chances, and how each one settles.

Classic picks (decision 51): result, double chance, over/under 1.5 / 2.5 / 3.5, both teams score.
New picks (decision 78): multigol, team goals, combos, 1X2 handicap and first-half picks. All of them come from the same
score matrix as the classic ones (first-half picks from its first-half version, matrix.HALF_SHARE), then a small
calibration correction p' = sigmoid(a + b * logit(p)) fitted on 2005-06 to 2016-17 and checked, untouched, on
2017-18 to 2023-24 and 2024-25 to 2025-26 (tools/markets.py, docs/strategy/2026-09-23-new-markets.md). Pick types that
failed the check are defined (so a pasted SNAI price or an old slip can still be read) but never offered.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .matrix import MAX_GOALS, MarketView


@dataclass(frozen=True)
class PickType:
    code: str
    group: str
    wins: Callable[[int, int], bool]   # (home goals, away goals) -> did the pick win; first-half picks take the half-time score
    chance: Callable[[MarketView], float]
    half: bool = False                 # settles on the first-half score
    parts: tuple[str, str] | None = None   # a combo's two picks


def _mask(f: Callable[[int, int], bool]) -> np.ndarray:
    return np.array([[bool(f(h, a)) for a in range(MAX_GOALS)] for h in range(MAX_GOALS)])


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


# The independent-goals matrix underrates "both teams score". A flat +1.5 point shift, fitted on 2005-06 to
# 2016-17 and checked on 2017-18 to 2023-24 (tools/btts.py): GG promised 60.0% -> happened 60.7% in the slip
# band; NG still 58.2% -> 56.5%, so GG is offered and NG is not (its chance would be ~1.7 points too kind).
BTTS_SHIFT = 0.015

_CLASSIC = [
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
]

# (a, b) of the calibration correction, fitted on 2005-06 to 2016-17 (results/markets.json)
CORR: dict[str, tuple[float, float]] = {
    "MG1-2": (-0.0016, 0.927), "MG1-3": (0.0574, 0.9312), "MG1-4": (0.1366, 0.9237), "MG1-5": (0.3954, 0.8042),
    "MG1-6": (-0.2255, 1.1318), "MG2-3": (-0.0563, 0.7654), "MG2-4": (0.0882, 0.7599), "MG2-5": (0.0334, 0.9193),
    "MG2-6": (0.0003, 0.9667), "MG3-4": (0.0355, 1.0445), "MG3-5": (0.0106, 1.0285), "MG3-6": (0.0064, 1.0235),
    "MG4-6": (0.0142, 1.0065),
    "HO05": (0.0272, 1.0164), "HO15": (-0.0013, 1.0086), "HU15": (0.0013, 1.0086), "HU25": (0.0865, 0.9925),
    "AO05": (0.0921, 0.9062), "AO15": (-0.0629, 0.9037), "AU15": (0.0629, 0.9037), "AU25": (0.2172, 0.8972),
    "HMG1-2": (0.0929, 0.9386), "HMG1-3": (0.0681, 1.0142), "AMG1-2": (0.0751, 0.7843), "AMG1-3": (0.0946, 0.8879),
    "1+O15": (-0.0374, 1.0084), "1+O25": (-0.03, 1.0014), "1+U35": (0.0453, 1.0086), "1+GG": (0.0859, 1.0347),
    "X+U25": (0.247, 1.2071), "X+U35": (0.247, 1.2071), "X+GG": (0.0307, 0.9841), "2+O15": (-0.0748, 0.9796),
    "2+O25": (-0.0857, 0.964), "2+U35": (0.0297, 1.0463), "2+GG": (-0.0008, 1.0043), "1X+O15": (-0.0013, 0.988),
    "1X+O25": (0.0038, 0.9882), "1X+U25": (0.0377, 1.0616), "1X+U35": (0.0157, 1.0431), "1X+GG": (0.0152, 0.9157),
    "X2+O15": (-0.0226, 0.9418), "X2+O25": (-0.0772, 0.915), "X2+U25": (0.0442, 1.1034), "X2+U35": (-0.0114, 1.0726),
    "X2+GG": (-0.0041, 0.9512), "12+O15": (-0.0859, 1.0816), "12+O25": (-0.0334, 1.0214), "12+U35": (0.0331, 0.7947),
    "12+GG": (-0.0763, 0.8693), "GG+O25": (-0.0345, 0.8266), "GG+U35": (-0.0783, 0.8894), "1X+MG1-3": (0.0421, 1.0379),
    "1X+MG1-4": (0.0406, 1.0214), "X2+MG1-3": (0.0124, 1.0513), "X2+MG1-4": (0.017, 1.018), "12+MG2-4": (-0.0003, 1.2047),
    "12+MG2-5": (-0.0625, 1.1527),
    "1H-1": (-0.1233, 0.9856), "XH-1": (0.2007, 1.0697), "2H-1": (-0.0034, 1.0042), "1H+1": (0.0229, 1.0095),
    "XH+1": (0.1593, 1.0928), "2H+1": (-0.1434, 0.9572), "1H-2": (-0.1785, 0.9956), "XH-2": (0.0355, 1.0378),
    "2H-2": (0.1233, 0.9856), "1H+2": (0.1434, 0.9572), "XH+2": (0.0424, 1.0387), "2H+2": (-0.3601, 0.8997),
    "1T1": (0.0098, 0.9937), "1TX": (0.0127, 1.0637), "1T2": (-0.0398, 0.9758), "1T1X": (0.0398, 0.9758),
    "1TX2": (-0.0098, 0.9937), "1T12": (-0.0127, 1.0637), "1TO05": (-0.017, 1.0816), "1TO15": (0.0186, 1.0283),
    "1TU15": (-0.0186, 1.0283), "1TU25": (0.0997, 0.9683), "1TU05": (0.017, 1.0816), "1TGG": (-0.3131, 0.7583),
    "1TNG": (0.3131, 0.7583),
}


def _mg(lo: int, hi: int):
    return lambda h, a: lo <= h + a <= hi


def _handicap(line: int, side: str):
    """European (1X2) handicap on the home side: the home score plus `line` against the away score."""
    def f(h, a):
        d = h - a + line
        return d > 0 if side == "1" else d == 0 if side == "X" else d < 0
    return f


_TEAM = {"HO05": lambda h, a: h >= 1, "HO15": lambda h, a: h >= 2, "HU15": lambda h, a: h <= 1, "HU25": lambda h, a: h <= 2,
         "AO05": lambda h, a: a >= 1, "AO15": lambda h, a: a >= 2, "AU15": lambda h, a: a <= 1, "AU25": lambda h, a: a <= 2,
         "HU05": lambda h, a: h == 0, "AU05": lambda h, a: a == 0,
         "HMG1-2": lambda h, a: 1 <= h <= 2, "HMG1-3": lambda h, a: 1 <= h <= 3,
         "AMG1-2": lambda h, a: 1 <= a <= 2, "AMG1-3": lambda h, a: 1 <= a <= 3}
_HALF = {"1T1": lambda h, a: h > a, "1TX": lambda h, a: h == a, "1T2": lambda h, a: h < a, "1T1X": lambda h, a: h >= a,
         "1TX2": lambda h, a: h <= a, "1T12": lambda h, a: h != a, "1TO05": lambda h, a: h + a >= 1, "1TO15": lambda h, a: h + a >= 2,
         "1TU15": lambda h, a: h + a <= 1, "1TU25": lambda h, a: h + a <= 2, "1TU05": lambda h, a: h + a == 0,
         "1TGG": lambda h, a: h >= 1 and a >= 1, "1TNG": lambda h, a: h == 0 or a == 0}
MULTIGOL = [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (2, 3), (2, 4), (2, 5), (2, 6), (3, 4), (3, 5), (3, 6), (4, 6)]
COMBOS = [("1", "O15"), ("1", "O25"), ("1", "U35"), ("1", "GG"), ("1", "NG"), ("X", "U25"), ("X", "U35"), ("X", "GG"),
          ("2", "O15"), ("2", "O25"), ("2", "U35"), ("2", "GG"), ("2", "NG"), ("1X", "O15"), ("1X", "O25"), ("1X", "U25"),
          ("1X", "U35"), ("1X", "GG"), ("X2", "O15"), ("X2", "O25"), ("X2", "U25"), ("X2", "U35"), ("X2", "GG"),
          ("12", "O15"), ("12", "O25"), ("12", "U35"), ("12", "GG"), ("GG", "O25"), ("GG", "U35"), ("NG", "U25"), ("NG", "O15"),
          ("1X", "MG1-3"), ("1X", "MG1-4"), ("X2", "MG1-3"), ("X2", "MG1-4"), ("12", "MG2-4"), ("12", "MG2-5")]

PICKS: dict[str, PickType] = {p.code: p for p in _CLASSIC}
MASKS: dict[str, np.ndarray] = {}


def _corrected(code: str, view: MarketView) -> float:
    pt = PICKS[code]
    m = view.half if pt.half else view.matrix
    raw = float(m[MASKS[code]].sum())
    if code not in CORR:   # never offered (left out before the check): the plain matrix chance
        return min(0.999, max(0.001, raw))
    a, b = CORR[code]
    p = _sigmoid(a + b * _logit(raw))
    if pt.parts:   # a combo can never be likelier than either of its parts
        p = min(p, *(PICKS[x].chance(view) for x in pt.parts))
    return min(0.999, max(0.001, p))


def _add(code: str, group: str, wins, half: bool = False, parts=None):
    PICKS[code] = PickType(code, group, wins, lambda v, c=code: _corrected(c, v), half, parts)
    MASKS[code] = _mask(wins)


for _lo, _hi in MULTIGOL:
    _add(f"MG{_lo}-{_hi}", "multigol", _mg(_lo, _hi))
for _c, _f in _TEAM.items():
    _add(_c, "team goals", _f)
for _x, _y in COMBOS:
    _fx, _fy = PICKS[_x].wins, PICKS[_y].wins
    _add(f"{_x}+{_y}", "combo", (lambda fx, fy: lambda h, a: fx(h, a) and fy(h, a))(_fx, _fy), parts=(_x, _y))
for _line in (-1, 1, -2, 2):
    for _side in ("1", "X", "2"):
        _add(f"{_side}H{_line:+d}", "handicap", _handicap(_line, _side))
for _c, _f in _HALF.items():
    _add(_c, "first half", _f, half=True)
for _p in _CLASSIC:
    MASKS[_p.code] = _mask(_p.wins)

# Not offered: NG and every pick that needs a team not to score (the matrix is too kind to them, decision 60 and the
# new-markets check), and the types that failed the check or confirm seasons, or had no band to judge (all under 30%).
NOT_OFFERED = frozenset({"NG", "1+NG", "2+NG", "NG+U25", "NG+O15", "HU05", "AU05", "AO05", "AO15", "X+GG", "2+U35", "1X+MG1-3",
                         "XH-1", "XH+1", "XH-2", "XH+2", "1T1", "1TGG"})
CLASSIC_MENU = frozenset(p.code for p in _CLASSIC) - {"NG"}
# The new pick types were checked from 30% up (the bands of the check): below that they are not offered.
NEW_FLOOR = 0.30
SLIP_MENU = frozenset(PICKS) - NOT_OFFERED
FULL_TIME_MENU = frozenset(c for c in SLIP_MENU if not PICKS[c].half)   # what the graded preset slips use (no half-time score needed)
GROUPS = ["result", "double chance", "goals", "both score", "multigol", "team goals", "combo", "handicap", "first half"]


@dataclass(frozen=True)
class Pick:
    match_id: str
    code: str
    chance: float  # fair chance that the pick wins
    odds: float    # the price the bookmaker offers


def settles(code: str, home_goals: int, away_goals: int, half_home: int | None = None, half_away: int | None = None) -> bool:
    """Did the pick win? First-half picks need the half-time score (ValueError without it)."""
    pt = PICKS[code]
    if pt.half:
        if half_home is None or half_away is None:
            raise ValueError(f"{code} settles on the half-time score, which is missing")
        return pt.wins(half_home, half_away)
    return pt.wins(home_goals, away_goals)


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
        if code not in CLASSIC_MENU and chance < NEW_FLOOR:
            continue
        if 0 < chance < 1:
            out.append(Pick(match_id, code, chance, float(price)))
    return out
