"""SNAI "sistema" bets: every k-leg accumulator that can be made from the n legs of a slip, each a separate ticket.

"n-1 su n" (one error allowed) is n tickets of n-1 legs; "n-2 su n" is n(n-1)/2 tickets of n-2 legs, and so on. The stake
is split equally across tickets. If every leg wins, every ticket pays; if m legs lose, only the tickets that avoid all
m losers pay. This module gives the exact chance of each outcome and what it pays, and the average return per euro.

SNAI rules (snai.it, guida, read 2026-09-22): at least EUR 0.05 per ticket and EUR 2 per system; at most EUR 10,000
won per ticket. Whether the Bonus Multipla applies to system tickets is not stated there, so it is an explicit switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb, prod

from .bonus import SNAI_MIN_ODDS

MIN_PER_TICKET = 0.05
MIN_PER_SYSTEM = 2.0
MAX_WIN_PER_TICKET = 10_000.0


def elementary(xs: list[float], k: int) -> float:
    """Sum over all k-subsets of the product of their values (e_k), by dynamic programme."""
    e = [1.0] + [0.0] * k
    for x in xs:
        for j in range(k, 0, -1):
            e[j] += e[j - 1] * x
    return e[k]


def bonus_for(k: int, odds: list[float], on: bool) -> float:
    """SNAI Bonus Multipla for a k-leg ticket (legs at 1.25+ count), if the switch says it applies to systems."""
    if not on:
        return 0.0
    n = sum(o >= SNAI_MIN_ODDS for o in odds)
    return 1.035 ** (min(n, 30) - 4) - 1 if n >= 5 else 0.0


@dataclass(frozen=True)
class Outcome:
    losers: int          # how many legs lost
    chance: float        # chance of exactly this many losers
    pays_min: float      # what the whole system pays back, worst case over which legs lost
    pays_max: float
    pays_avg: float      # average payout given this many losers


@dataclass(frozen=True)
class SistemaPlan:
    n: int
    k: int
    tickets: int
    per_ticket: float
    min_stake: float
    chance_any: float        # chance that at least one ticket pays
    chance_profit: float     # chance the payout exceeds the stake
    average_return: float    # expected payout per euro staked
    outcomes: list[Outcome]


def plan(legs: list[tuple[float, float]], k: int, stake: float, bonus_on: bool = False) -> SistemaPlan:
    """legs: (chance, odds) per leg. k: legs per ticket (k == n is the plain accumulator). Tickets whose legs all have
    odds >= 1.25 get the bonus if bonus_on (applied per ticket, on the ticket's own leg count)."""
    n = len(legs)
    if not 1 <= k <= n:
        raise ValueError("k must be between 1 and the number of legs")
    if n - k > 3 and n > 12:
        raise ValueError("at most three errors on slips longer than 12 legs")
    tickets = comb(n, k)
    per = stake / tickets
    idx = range(n)

    def payout(winners: list[int]) -> float:
        # sum over winning tickets of per * prod(odds) * (1 + bonus); the bonus depends only on the ticket's leg count
        # when every leg is at 1.25+ (the usual case); otherwise it is computed ticket by ticket
        if len(winners) < k:
            return 0.0
        os = [legs[i][1] for i in winners]
        if not bonus_on:
            return min(per * elementary(os, k), MAX_WIN_PER_TICKET * comb(len(winners), k))
        return sum(min(per * prod(c) * (1 + bonus_for(k, list(c), True)), MAX_WIN_PER_TICKET) for c in combinations(os, k))

    outcomes, chance_profit = [], 0.0
    for m in range(0, n - k + 1):
        tot = lo = hi = acc = None
        for losers in combinations(idx, m):
            ls = set(losers)
            pr = prod((1 - legs[i][0]) if i in ls else legs[i][0] for i in idx)
            pay = payout([i for i in idx if i not in ls])
            tot = pr if tot is None else tot + pr
            acc = pr * pay if acc is None else acc + pr * pay
            lo = pay if lo is None else min(lo, pay)
            hi = pay if hi is None else max(hi, pay)
            if pay > stake:
                chance_profit += pr
        outcomes.append(Outcome(m, tot, lo, hi, acc / tot if tot else 0.0))
    chance_any = sum(o.chance for o in outcomes)
    expected = sum(o.chance * o.pays_avg for o in outcomes)
    return SistemaPlan(n, k, tickets, per, max(MIN_PER_SYSTEM, MIN_PER_TICKET * tickets), chance_any, chance_profit,
                       expected / stake if stake else 0.0, outcomes)
