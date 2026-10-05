"""The live model (decision 87): a pick's chance while the match is being played.

The goal rate of a side in a given minute = its pre-match expected goals x the minute's profile (goals come slower in the
first minutes, faster late and in stoppage time) x the score-state multiplier (a side one goal down scores about 14% more
often, two or more down 23% more; a side one up 6% more; two or more up as at level) x the red-card multipliers (a side
with a player sent off scores about a third less, its opponent about 80% more), scaled so that at kick-off the model
returns the pre-match expected goals. Fitted on 1,136 league matches with pre-match prices (tools/live_fit.py, StatsBomb
open data + Bet365 prices); the numbers live in results/live_model.json and are copied into index.html (LIVE_MODEL),
whose `inplay` mirrors `chance` here to 1e-9 (tests/js/engine.test.js).

    chance("1", lh=1.5, la=1.0, h=0, a=1, minute=60, second_half=True)                 # the home side trails 0-1 after an hour
    chance("O25", lh, la, h, a, minute=30, second_half=False, reds=(1, 0))             # a red card for the home side
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .picks import PICKS

MODEL_PATH = Path(__file__).resolve().parents[1] / "results" / "live_model.json"
GOALS = 11   # goals still to come, per side, tracked by the chain (the rest is negligible)


@lru_cache(maxsize=1)
def model(path: str = str(MODEL_PATH)) -> dict:
    return json.loads(Path(path).read_text())


def steps(second_half: bool, minute: float, to_half_time: bool = False, m: dict | None = None) -> list[tuple[int, float]]:
    """The minutes still to play from the clock minute shown: (bin, exposure). Bins 0-17 are the 5-minute bins of regular
    time, 18 and 19 the two stoppage periods (their average length, less what has already been played of them)."""
    m = m or model()
    out: list[tuple[int, float]] = []
    if not second_half:
        for k in range(max(0, min(45, int(minute))), 45):
            out.append((k // 5, 1.0))
        out.append((18, m["stoppage"]["1"]["len"] if minute < 45 else max(0.3, m["stoppage"]["1"]["len"] - (minute - 45))))
        if to_half_time:
            return out
        minute = 45
    for k in range(max(45, min(90, int(minute))), 90):
        out.append((k // 5, 1.0))
    out.append((19, m["stoppage"]["2"]["len"] if minute < 90 else max(0.3, m["stoppage"]["2"]["len"] - (minute - 90))))
    return out


def state_mul(diff: int, m: dict | None = None) -> float:
    s = (m or model())["state"]
    if diff == 0:
        return 1.0
    if diff == 1:
        return s["lead1"]
    if diff >= 2:
        return s["lead2"]
    return s["trail1"] if diff == -1 else s["trail2"]


def rate(lam: float, bin_: int, diff: int, own_red: int, opp_red: int, m: dict | None = None) -> float:
    """Expected goals of one side in one minute of play."""
    m = m or model()
    f = m["stoppage"]["1" if bin_ == 18 else "2"]["f"] if bin_ >= 18 else m["bins"][bin_]
    return lam * f * state_mul(diff, m) * m["red"]["own"] ** own_red * m["red"]["opp"] ** opp_red / 90.0 / m.get("scale", 1.0)


def distribution(lh: float, la: float, h: int, a: int, steps_: list[tuple[int, float]], rh: int = 0, ra: int = 0,
                 m: dict | None = None) -> list[list[float]]:
    """The chance of every (goals still to come home, away) after the given steps: a Markov chain minute by minute, both
    sides may score in the same minute."""
    m = m or model()
    dist = [[0.0] * GOALS for _ in range(GOALS)]
    dist[0][0] = 1.0
    for bin_, e in steps_:
        nd = [[0.0] * GOALS for _ in range(GOALS)]
        for x in range(GOALS):
            row = dist[x]
            for y in range(GOALS):
                p = row[y]
                if not p:
                    continue
                diff = (h + x) - (a + y)
                ph = 1 - math.exp(-rate(lh, bin_, diff, rh, ra, m) * e)
                pa = 1 - math.exp(-rate(la, bin_, -diff, ra, rh, m) * e)
                xx, yy = min(GOALS - 1, x + 1), min(GOALS - 1, y + 1)
                nd[x][y] += p * (1 - ph) * (1 - pa)
                nd[xx][y] += p * ph * (1 - pa)
                nd[x][yy] += p * (1 - ph) * pa
                nd[xx][yy] += p * ph * pa
        dist = nd
    return dist


def chance(code: str, lh: float, la: float, h: int, a: int, minute: float, second_half: bool, finished: bool = False,
           hh: int | None = None, ha: int | None = None, reds: tuple[int, int] = (0, 0), half_time_break: bool = False,
           m: dict | None = None) -> float:
    """A pick's chance now (mirrors index.html's inplay)."""
    m = m or model()
    pt = PICKS[code]
    if pt.half:
        if hh is not None and ha is not None and hh >= 0:
            return 1.0 if pt.wins(hh, ha) else 0.0
        if finished or second_half or half_time_break:
            return 1.0 if pt.wins(h, a) else 0.0
        dist = distribution(lh, la, h, a, steps(False, minute, True, m), reds[0], reds[1], m)
    else:
        if finished:
            return 1.0 if pt.wins(h, a) else 0.0
        second = second_half or half_time_break
        start = 45 if half_time_break and not second_half else minute
        dist = distribution(lh, la, h, a, steps(second, start, False, m), reds[0], reds[1], m)
    return sum(dist[x][y] for x in range(GOALS) for y in range(GOALS) if dist[x][y] and pt.wins(h + x, a + y))


def expected_goals_at_kickoff(lh: float, la: float, m: dict | None = None) -> tuple[float, float]:
    """What the chain delivers from 0-0 at kick-off: used by the fit to set `scale` so this equals (lh, la)."""
    m = m or model()
    dist = distribution(lh, la, 0, 0, steps(False, 0, False, m), 0, 0, m)
    eh = sum(x * dist[x][y] for x in range(GOALS) for y in range(GOALS))
    ea = sum(y * dist[x][y] for x in range(GOALS) for y in range(GOALS))
    return eh, ea
