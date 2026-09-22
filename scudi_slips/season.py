"""What a season of slips looks like in money: hits, dry runs and the spread of outcomes.

Every slip is an independent coin with its own chance and its own payout, so the whole season can be
simulated exactly by drawing each slip once. `simulate` returns the numbers a person needs before deciding
stakes: how many hits to expect, how long the dry runs get, and how wide the range of season results is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SlipPlan:
    chance: float          # chance that every leg wins
    payout: float          # what €1 returns if it lands, bonus included (odds × (1 + bonus))
    stake: float           # euros per slip
    per_week: float = 1.0  # how many such slips a week


@dataclass(frozen=True)
class SeasonOutlook:
    weeks: int
    slips: int
    staked: float
    expected_hits: float
    expected_profit: float
    profit_p5: float
    profit_p50: float
    profit_p95: float
    chance_of_loss: float
    chance_of_zero_hits: float
    longest_dry_run_p50: int
    longest_dry_run_p90: int
    hits_p5: int
    hits_p95: int


def simulate(plans: list[SlipPlan], weeks: int = 38, sims: int = 20000, seed: int = 7) -> SeasonOutlook:
    if not plans or weeks < 1:
        raise ValueError("need at least one slip plan and one week")
    rng = np.random.default_rng(seed)
    chances, payouts, stakes = [], [], []
    for p in plans:
        if not (0 < p.chance < 1) or p.payout <= 0 or p.stake <= 0 or p.per_week <= 0:
            raise ValueError(f"bad plan {p}")
        for _ in range(round(p.per_week * weeks)):
            chances.append(p.chance)
            payouts.append(p.payout)
            stakes.append(p.stake)
    chances, payouts, stakes = (np.array(x) for x in (chances, payouts, stakes))
    n = len(chances)
    hits = rng.random((sims, n)) < chances                       # shape sims × slips, in season order
    profit = (hits * payouts * stakes).sum(axis=1) - stakes.sum()
    # longest run of misses in each simulated season
    dry = np.zeros(sims, dtype=int)
    run = np.zeros(sims, dtype=int)
    for j in range(n):
        run = np.where(hits[:, j], 0, run + 1)
        dry = np.maximum(dry, run)
    nh = hits.sum(axis=1)
    return SeasonOutlook(
        weeks=weeks, slips=n, staked=float(stakes.sum()),
        expected_hits=float(chances.sum()), expected_profit=float((chances * payouts * stakes).sum() - stakes.sum()),
        profit_p5=float(np.percentile(profit, 5)), profit_p50=float(np.percentile(profit, 50)), profit_p95=float(np.percentile(profit, 95)),
        chance_of_loss=float((profit < 0).mean()), chance_of_zero_hits=float((nh == 0).mean()),
        longest_dry_run_p50=int(np.percentile(dry, 50)), longest_dry_run_p90=int(np.percentile(dry, 90)),
        hits_p5=int(np.percentile(nh, 5)), hits_p95=int(np.percentile(nh, 95)),
    )
