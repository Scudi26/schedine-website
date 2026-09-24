"""Structure questions: how many Serie A legs, and whether SNAI's bonus should count toward the target.

Run after tools/backtest.py (it reuses results/priced.json). Both-teams-score picks are excluded here,
because the calibration step of the backtest showed the score matrix misprices them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, settles, snai_bonus, solve
from tools.backtest import MIN_ODDS, OUT, load, serie_a_rounds, weekend_pools


def run(df, priced, groups, legs, target, bonus_in_target=False, label=""):
    recs = []
    for ids in groups:
        menus = [[Pick(str(i), c, priced[i]["chances"][c], priced[i]["offered"][c]) for c in priced[i]["offered"]
                  if c in SLIP_MENU and priced[i]["offered"][c] >= MIN_ODDS] for i in ids]
        raw_target = target / (1.035 ** (legs - 4)) if (bonus_in_target and legs >= 5) else target
        slip = solve(menus, raw_target, legs=legs, grid=0.001 if len(ids) <= 12 else 0.002)
        if slip is None:
            continue
        won = all(settles(p.code, df.at[int(p.match_id), "FTHome"], df.at[int(p.match_id), "FTAway"]) for p in slip.picks)
        recs.append((slip.chance, slip.odds, won, snai_bonus([p.odds for p in slip.picks])))
    n = len(recs)
    expected = sum(r[0] for r in recs)
    out = {"label": label, "legs": legs, "target": target, "bonus_in_target": bonus_in_target, "slips": n,
           "predicted_1_in": round(n / expected, 1), "expected_hits": round(expected, 1), "actual_hits": int(sum(r[2] for r in recs)),
           "avg_odds": round(float(np.mean([r[1] for r in recs])), 1),
           "avg_payout_multiple": round(float(np.mean([r[1] * (1 + r[3]) for r in recs])), 1),
           "predicted_return_snai": round(float(np.mean([r[0] * r[1] * (1 + r[3]) for r in recs])), 3),
           "actual_return_snai": round(float(np.mean([r[1] * (1 + r[3]) if r[2] else 0 for r in recs])), 3)}
    print(json.dumps(out), flush=True)
    return out


def main():
    df = load()
    priced = {int(k): v for k, v in json.loads((OUT / "priced.json").read_text()).items()}
    rounds, pools = serie_a_rounds(df), weekend_pools(df)
    res = [run(df, priced, rounds, legs, 25, label="Serie A best-k of the round") for legs in (5, 6, 7, 8, 9, 10)]
    res += [run(df, priced, rounds, legs, 50, label="Serie A best-k of the round") for legs in (6, 8, 10)]
    res.append(run(df, priced, rounds, 10, 25, bonus_in_target=True, label="Serie A all 10, bonus counts toward 25x"))
    res.append(run(df, priced, pools, 10, 25, label="Top 5 best 10"))
    res.append(run(df, priced, pools, 10, 25, bonus_in_target=True, label="Top 5 best 10, bonus counts toward 25x"))
    res.append(run(df, priced, pools, 10, 50, label="Top 5 best 10"))
    (OUT / "variants.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
