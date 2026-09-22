"""What do the user's rules cost? Top-5 weekends and Serie A rounds under different menus, leg counts and league rules."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, settles, snai_bonus, solve
from tools.backtest import MIN_ODDS, OUT, load, serie_a_rounds, weekend_pools

MENUS = {"results only": {"1", "X", "2"}, "results + double chance": {"1", "X", "2", "1X", "X2", "12"}, "everything": set(SLIP_MENU)}
_STATE = {}


def _init():
    df = load()
    _STATE["df"] = df
    _STATE["priced"] = {int(k): v for k, v in json.loads((OUT / "priced.json").read_text()).items()}
    _STATE["rounds"] = serie_a_rounds(df)
    _STATE["pools"] = weekend_pools(df)


def run(job):
    pool_name, legs, target, menu_name, limits, group_max = job
    if not _STATE:
        _init()
    df, priced = _STATE["df"], _STATE["priced"]
    groups_of = _STATE["rounds"] if pool_name == "Serie A round" else _STATE["pools"]
    codes = MENUS[menu_name]
    recs = []
    for ids in groups_of:
        menus = [[Pick(str(i), c, priced[i]["chances"][c], priced[i]["offered"][c]) for c in priced[i]["offered"]
                  if c in codes and priced[i]["offered"][c] >= MIN_ODDS] for i in ids]
        labels = [df.at[i, "Division"] for i in ids]
        slip = solve(menus, target, legs=legs, grid=0.002, groups=labels, group_limits=limits, default_group_max=group_max, refine=False)
        if slip is None:
            continue
        won = all(settles(p.code, df.at[int(p.match_id), "FTHome"], df.at[int(p.match_id), "FTAway"]) for p in slip.picks)
        recs.append((slip.chance, slip.odds, won, snai_bonus([p.odds for p in slip.picks])))
    n = len(recs)
    if not n:
        return {"pool": pool_name, "legs": legs, "target": target, "menu": menu_name, "slips": 0}
    expected = sum(r[0] for r in recs)
    return {"pool": pool_name, "legs": legs, "target": target, "menu": menu_name, "limits": limits, "group_max": group_max,
            "slips": n, "built_share": round(n / len(groups_of), 3), "predicted_1_in": round(n / expected, 1),
            "expected_hits": round(expected, 1), "actual_hits": int(sum(r[2] for r in recs)),
            "avg_odds": round(float(np.mean([r[1] for r in recs])), 1),
            "predicted_return_snai": round(float(np.mean([r[0] * r[1] * (1 + r[3]) for r in recs])), 3),
            "actual_return_snai": round(float(np.mean([r[1] * (1 + r[3]) if r[2] else 0 for r in recs])), 3)}


def main():
    jobs = [("Top 5 weekend", legs, 25, m, {}, None) for m in MENUS for legs in (5, 6, 8, 10, 12)]
    jobs += [("Serie A round", legs, 25, "results only", {}, None) for legs in (5, 6, 7, 8)]
    jobs += [("Top 5 weekend", 10, 25, "everything", {"I1": (5, None)}, None),
             ("Top 5 weekend", 10, 25, "everything", {}, 2),
             ("Top 5 weekend", 10, 50, "results only", {}, None)]
    out = []
    with ProcessPoolExecutor(max_workers=2) as ex:
        for res in ex.map(run, jobs):
            print(json.dumps(res), flush=True)
            out.append(res)
    (OUT / "rules.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
