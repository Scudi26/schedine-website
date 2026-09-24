"""Backtest the slip builder on past seasons of the five big leagues.

Data: huggingface.co/datasets/xgabora/club-football-match-data (built from football-data.co.uk):
Bet365 pre-match prices for the result and over/under 2.5, plus final scores.
Development seasons only: 2005-06 to 2023-24. 2024-25 onwards is left untouched.

What is real and what is assumed:
  * chances: from Bet365's own prices with the margin removed (power method) -> real market view
  * result and over/under 2.5 prices: real Bet365 prices
  * double-chance prices: derived from Bet365's result prices the way bookmakers derive them
  * over 1.5 / under 3.5 / both-score prices: fair price shaved by the match's over/under margin + 1-1.5 points (ASSUMED)
  * SNAI's prices are not in any free historical file; money figures are at Bet365-like prices
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import PICKS, Pick, fit_market, power_devig, settles, snai_bonus, solve

DATA = Path(__file__).resolve().parents[1] / "data" / "Matches.csv"
OUT = Path(__file__).resolve().parents[1] / "results"
LEAGUES = {"I1": "Serie A", "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "F1": "Ligue 1"}
FIRST_SEASON, LAST_SEASON = 2005, 2023
TARGETS = [25, 30, 40, 50]
MIN_ODDS = 1.25
REAL_PRICE_CODES = {"1", "X", "2", "O25", "U25"}


def floor2(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def price_match(row: tuple) -> dict | None:
    idx, oh, od, oa, oo, ou = row
    try:
        ph, pd_, pa = power_devig([oh, od, oa])
        po, _ = power_devig([oo, ou])
        view = fit_market(ph, pd_, pa, po)
    except ValueError:
        return None
    ou_margin = 1 / oo + 1 / ou - 1
    offered = {"1": oh, "X": od, "2": oa, "O25": oo, "U25": ou,
               "1X": floor2(1 / (1 / oh + 1 / od)), "X2": floor2(1 / (1 / oa + 1 / od)), "12": floor2(1 / (1 / oh + 1 / oa))}
    chances = {code: PICKS[code].chance(view) for code in PICKS}
    for code, extra in (("O15", 0.010), ("U35", 0.010), ("GG", 0.015), ("NG", 0.015)):
        offered[code] = max(1.01, floor2(1 / (chances[code] * (1 + ou_margin + extra))))
    return {"idx": idx, "chances": chances, "offered": offered, "fit_error": view.fit_error, "lh": view.lh, "la": view.la, "rho": view.rho}


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA, low_memory=False)
    df = df[df["Division"].isin(LEAGUES)].copy()
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


def serie_a_rounds(df: pd.DataFrame) -> list[list[int]]:
    """Group Serie A matches into rounds: a new round starts when a team would appear twice or 4 days have passed."""
    rounds = []
    for _, g in df[df["Division"] == "I1"].groupby("season"):
        cur, teams, start = [], set(), None
        for i, r in g.iterrows():
            if cur and (r.HomeTeam in teams or r.AwayTeam in teams or (r.date - start).days > 4):
                rounds.append(cur)
                cur, teams, start = [], set(), None
            if start is None:
                start = r.date
            cur.append(i)
            teams.update((r.HomeTeam, r.AwayTeam))
        if cur:
            rounds.append(cur)
    return [r for r in rounds if len(r) == 10]


def weekend_pools(df: pd.DataFrame) -> list[list[int]]:
    """All five leagues, Friday to Monday, keyed by that Friday. Only busy weekends (25+ matches)."""
    wd = df["date"].dt.weekday
    sel = df[wd.isin([4, 5, 6, 0])].copy()
    sel["friday"] = sel["date"] - pd.to_timedelta((sel["date"].dt.weekday - 4) % 7, unit="D")
    pools = []
    for _, g in sel.groupby("friday"):
        teams = pd.concat([g.HomeTeam, g.AwayTeam])
        if len(g) >= 25 and not teams.duplicated().any():
            pools.append(list(g.index))
    return pools


def build(priced: dict, ids: list[int], target: float, legs: int, codes: set[str] | None):
    menus = []
    for i in ids:
        p = priced[i]
        menus.append([Pick(str(i), c, p["chances"][c], p["offered"][c]) for c in p["offered"]
                      if (codes is None or c in codes) and p["offered"][c] >= MIN_ODDS and 0 < p["chances"][c] < 1])
    return solve(menus, target, legs=legs, grid=0.001 if len(ids) <= 12 else 0.002)


def evaluate(df, priced, groups, legs, codes, label):
    rows = []
    for target in TARGETS:
        recs = []
        for ids in groups:
            slip = build(priced, ids, target, legs, codes)
            if slip is None:
                continue
            won = all(settles(p.code, df.at[int(p.match_id), "FTHome"], df.at[int(p.match_id), "FTAway"]) for p in slip.picks)
            bonus = snai_bonus([p.odds for p in slip.picks])
            recs.append({"chance": slip.chance, "odds": slip.odds, "won": won, "bonus": bonus,
                         "season": int(df.at[int(slip.picks[0].match_id), "season"]), "codes": [p.code for p in slip.picks],
                         "leg_chance": [p.chance for p in slip.picks]})
        n = len(recs)
        exp = sum(r["chance"] for r in recs)
        hits = sum(r["won"] for r in recs)
        ret = np.array([r["odds"] if r["won"] else 0.0 for r in recs])
        retb = np.array([r["odds"] * (1 + r["bonus"]) if r["won"] else 0.0 for r in recs])
        rng = np.random.default_rng(7)
        boot = [retb[rng.integers(0, n, n)].mean() for _ in range(4000)]
        mix = pd.Series([c for r in recs for c in r["codes"]]).value_counts(normalize=True).round(3).to_dict()
        rows.append({"slip": label, "target": target, "slips": n, "expected_hits": round(exp, 1), "actual_hits": int(hits),
                     "predicted_rate": round(exp / n, 4), "actual_rate": round(hits / n, 4),
                     "z": round((hits - exp) / math.sqrt(sum(r["chance"] * (1 - r["chance"]) for r in recs)), 2),
                     "avg_odds": round(float(np.mean([r["odds"] for r in recs])), 2),
                     "predicted_return_no_bonus": round(float(np.mean([r["chance"] * r["odds"] for r in recs])), 3),
                     "actual_return_no_bonus": round(float(ret.mean()), 3),
                     "predicted_return_snai_bonus": round(float(np.mean([r["chance"] * r["odds"] * (1 + r["bonus"]) for r in recs])), 3),
                     "actual_return_snai_bonus": round(float(retb.mean()), 3),
                     "actual_return_snai_90pct": [round(float(np.percentile(boot, 5)), 3), round(float(np.percentile(boot, 95)), 3)],
                     "pick_mix": mix})
        print(json.dumps(rows[-1]), flush=True)
    return rows


def calibration(df, priced):
    out = {}
    for code in PICKS:
        pred = np.array([priced[i]["chances"][code] for i in priced])
        won = np.array([settles(code, df.at[i, "FTHome"], df.at[i, "FTAway"]) for i in priced])
        band = (pred >= 0.55) & (pred <= 0.85)   # where slip legs live
        offered = np.array([priced[i]["offered"][code] for i in priced])
        rec = {"matches": len(pred), "predicted": round(float(pred.mean()), 4), "actual": round(float(won.mean()), 4),
               "band_n": int(band.sum()), "band_predicted": round(float(pred[band].mean()), 4) if band.any() else None,
               "band_actual": round(float(won[band].mean()), 4) if band.any() else None,
               "band_flat_return": round(float((won[band] * offered[band]).mean()), 4) if band.any() else None}
        buckets = []
        for lo in np.arange(0.5, 0.9, 0.05):
            m = (pred >= lo) & (pred < lo + 0.05)
            if m.sum() >= 150:
                buckets.append({"from": round(float(lo), 2), "n": int(m.sum()), "predicted": round(float(pred[m].mean()), 3), "actual": round(float(won[m].mean()), 3)})
        rec["buckets"] = buckets
        out[code] = rec
    return out


def main():
    OUT.mkdir(exist_ok=True)
    df = load()
    print(f"{len(df)} matches, seasons {df.season.min()}-{df.season.max()}, by league: {df.Division.value_counts().to_dict()}", flush=True)
    rows = [(i, r.OddHome, r.OddDraw, r.OddAway, r.Over25, r.Under25) for i, r in df.iterrows()]
    cache = OUT / "priced.json"
    if cache.exists():
        priced = {int(k): v for k, v in json.loads(cache.read_text()).items()}
    else:
        with ProcessPoolExecutor() as ex:
            priced = {p["idx"]: p for p in ex.map(price_match, rows, chunksize=500) if p}
        cache.write_text(json.dumps(priced))
    errs = np.array([p["fit_error"] for p in priced.values()])
    print(f"priced {len(priced)}; fit error median {np.median(errs):.5f}, 99th pct {np.percentile(errs, 99):.5f}, max {errs.max():.4f}", flush=True)
    df = df.loc[list(priced)]
    result = {"matches": len(priced), "seasons": [FIRST_SEASON, LAST_SEASON], "fit_error_p99": float(np.percentile(errs, 99))}
    result["calibration"] = calibration(df, priced)
    for code, c in result["calibration"].items():
        print(code, c["predicted"], c["actual"], "| band", c["band_n"], c["band_predicted"], c["band_actual"], "flat return", c["band_flat_return"], flush=True)

    rounds = [r for r in serie_a_rounds(df) if all(i in priced for i in r)]
    pools = weekend_pools(df)
    print(f"Serie A full rounds: {len(rounds)}; busy weekends: {len(pools)} (avg {np.mean([len(p) for p in pools]):.0f} matches)", flush=True)
    result["slips"] = []
    result["slips"] += evaluate(df, priced, rounds, 10, None, "Serie A, all 10 matches, full menu")
    result["slips"] += evaluate(df, priced, rounds, 10, REAL_PRICE_CODES, "Serie A, all 10 matches, real-price picks only")
    result["slips"] += evaluate(df, priced, pools, 10, None, "Top 5 leagues, best 10, full menu")
    result["slips"] += evaluate(df, priced, pools, 10, REAL_PRICE_CODES, "Top 5 leagues, best 10, real-price picks only")

    # the naive slip most people play: the favourite to win in all ten Serie A matches
    naive = []
    for ids in rounds:
        ch, od, won = 1.0, 1.0, True
        for i in ids:
            p = priced[i]
            code = max(("1", "X", "2"), key=lambda c: p["chances"][c])
            ch *= p["chances"][code]
            od *= p["offered"][code]
            won &= settles(code, df.at[i, "FTHome"], df.at[i, "FTAway"])
        naive.append((ch, od, won))
    result["naive_ten_favourites"] = {"slips": len(naive), "median_odds": round(float(np.median([n[1] for n in naive])), 1),
                                      "expected_hits": round(sum(n[0] for n in naive), 2), "actual_hits": int(sum(n[2] for n in naive)),
                                      "actual_return": round(float(np.mean([n[1] if n[2] else 0 for n in naive])), 3)}
    print(result["naive_ten_favourites"], flush=True)
    (OUT / "backtest.json").write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
