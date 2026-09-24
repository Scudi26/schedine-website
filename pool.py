"""Does a wider pool of matches make the weekend slip better?

Compares, on the same weekends, the best 10-leg slip at 25x built from (a) the top-5 leagues only and
(b) the top-5 leagues plus the five second divisions (Serie B, Championship, La Liga 2, 2. Bundesliga, Ligue 2),
and (c) also the Dutch, Portuguese, Belgian and Turkish top flights, all of which SNAI prices.
First checks that Bet365's chances are as well calibrated in those leagues as in the top five.
Development seasons only (2005-06 to 2023-24).
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, settles, snai_bonus, solve
from tools.backtest import DATA, FIRST_SEASON, LAST_SEASON, MIN_ODDS, OUT, price_match

TOP5 = ["I1", "E0", "SP1", "D1", "F1"]
SECOND = ["I2", "E1", "SP2", "D2", "F2"]
OTHER = ["N1", "P1", "B1", "T1"]
NAMES = {"I1": "Serie A", "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "F1": "Ligue 1", "I2": "Serie B", "E1": "Championship",
         "SP2": "La Liga 2", "D2": "2. Bundesliga", "F2": "Ligue 2", "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Belgian Pro League", "T1": "Süper Lig"}


def load_all(divs):
    df = pd.read_csv(DATA, low_memory=False)
    df = df[df["Division"].isin(divs)].copy()
    df["date"] = pd.to_datetime(df["MatchDate"], errors="coerce")
    df = df.dropna(subset=["date", "FTHome", "FTAway", "OddHome", "OddDraw", "OddAway", "Over25", "Under25"])
    for c in ["OddHome", "OddDraw", "OddAway", "Over25", "Under25"]:
        df = df[df[c] > 1.0]
    df["season"] = np.where(df["date"].dt.month >= 7, df["date"].dt.year, df["date"].dt.year - 1)
    df = df[(df["season"] >= FIRST_SEASON) & (df["season"] <= LAST_SEASON)]
    df = df.sort_values(["date", "Division", "HomeTeam"]).reset_index(drop=True)
    df["FTHome"] = df["FTHome"].astype(int)
    df["FTAway"] = df["FTAway"].astype(int)
    return df


def price_all(df, cache):
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}
    rows = [(i, r.OddHome, r.OddDraw, r.OddAway, r.Over25, r.Under25) for i, r in df.iterrows()]
    with ProcessPoolExecutor() as ex:
        priced = {p["idx"]: p for p in ex.map(price_match, rows, chunksize=500) if p and p["fit_error"] < 0.01}
    cache.write_text(json.dumps(priced))
    return priced


def calibration_by_division(df, priced):
    out = {}
    for div, g in df.groupby("Division"):
        ids = [i for i in g.index if i in priced]
        rec = {"matches": len(ids)}
        for code in ["1", "2", "1X", "X2", "12", "O15", "O25", "U25", "U35"]:
            pred = np.array([priced[i]["chances"][code] for i in ids])
            won = np.array([settles(code, df.at[i, "FTHome"], df.at[i, "FTAway"]) for i in ids])
            band = (pred >= 0.55) & (pred <= 0.85)
            if band.sum() >= 300:
                rec[code] = [round(float(pred[band].mean()), 3), round(float(won[band].mean()), 3), int(band.sum())]
        gaps = [abs(v[0] - v[1]) for k, v in rec.items() if k != "matches"]
        rec["worst_gap_points"] = round(max(gaps) * 100, 1) if gaps else None
        out[div] = rec
    return out


def weekend_pools(df, divs):
    sel = df[df["Division"].isin(divs)]
    sel = sel[sel["date"].dt.weekday.isin([4, 5, 6, 0])].copy()
    sel["friday"] = sel["date"] - pd.to_timedelta((sel["date"].dt.weekday - 4) % 7, unit="D")
    pools = {}
    for fri, g in sel.groupby("friday"):
        teams = pd.concat([g.HomeTeam, g.AwayTeam])
        if not teams.duplicated().any():
            pools[fri] = list(g.index)
    return pools


def run(df, priced, pools, legs, target, label):
    recs = []
    for ids in pools:
        ids = [i for i in ids if i in priced]
        menus = [[Pick(str(i), c, priced[i]["chances"][c], priced[i]["offered"][c]) for c in priced[i]["offered"]
                  if c in SLIP_MENU and priced[i]["offered"][c] >= MIN_ODDS] for i in ids]
        slip = solve(menus, target, legs=legs, grid=0.002, refine=False)
        if slip is None:
            continue
        won = all(settles(p.code, df.at[int(p.match_id), "FTHome"], df.at[int(p.match_id), "FTAway"]) for p in slip.picks)
        divs = [df.at[int(p.match_id), "Division"] for p in slip.picks]
        recs.append((slip.chance, slip.odds, won, snai_bonus([p.odds for p in slip.picks]), divs))
    n = len(recs)
    exp = sum(r[0] for r in recs)
    mix = pd.Series([d for r in recs for d in r[4]]).value_counts(normalize=True).round(3).to_dict()
    out = {"pool": label, "legs": legs, "target": target, "weekends": n, "predicted_1_in": round(n / exp, 1), "expected_hits": round(exp, 1),
           "actual_hits": int(sum(r[2] for r in recs)), "avg_pool_size": round(float(np.mean([len(p) for p in pools])), 1),
           "predicted_return_snai": round(float(np.mean([r[0] * r[1] * (1 + r[3]) for r in recs])), 3),
           "actual_return_snai": round(float(np.mean([r[1] * (1 + r[3]) if r[2] else 0 for r in recs])), 3), "league_mix": mix}
    print(json.dumps(out), flush=True)
    return out


def main():
    OUT.mkdir(exist_ok=True)
    df = load_all(TOP5 + SECOND + OTHER)
    priced = price_all(df, OUT / "priced_wide.json")
    print(f"{len(priced)} matches priced", flush=True)
    cal = calibration_by_division(df, priced)
    for d, r in cal.items():
        print(NAMES[d], r["matches"], "worst gap", r["worst_gap_points"], "| home win", r.get("1"), "| over 2.5", r.get("O25"), flush=True)
    top = weekend_pools(df, TOP5)
    wide = weekend_pools(df, TOP5 + SECOND)
    widest = weekend_pools(df, TOP5 + SECOND + OTHER)
    common = [k for k in top if k in wide and k in widest and len(top[k]) >= 25]
    print(f"{len(common)} weekends compared", flush=True)
    res = {"calibration": cal, "slips": []}
    for target in (25, 50):
        res["slips"].append(run(df, priced, [top[k] for k in common], 10, target, "top 5"))
        res["slips"].append(run(df, priced, [wide[k] for k in common], 10, target, "top 5 + second divisions"))
        res["slips"].append(run(df, priced, [widest[k] for k in common], 10, target, "top 5 + second divisions + NL/PT/BE/TR"))
    (OUT / "pool.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
