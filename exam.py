"""The go-live exam: docs/strategy/2026-09-22-slips-golive-exam.md, run once on the sealed seasons 2024-25 and 2025-26."""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, settles, snai_bonus, solve
from tools.backtest import DATA, LEAGUES, MIN_ODDS, OUT, price_match, serie_a_rounds, weekend_pools

EXAM_SEASONS = (2024, 2025)
DEV_1_IN = {6: 29.4, 8: 30.6, 10: 33.2}


def load_exam():
    df = pd.read_csv(DATA, low_memory=False)
    df = df[df["Division"].isin(LEAGUES)].copy()
    df["date"] = pd.to_datetime(df["MatchDate"], errors="coerce")
    df = df.dropna(subset=["date", "FTHome", "FTAway", "OddHome", "OddDraw", "OddAway", "Over25", "Under25"])
    for c in ["OddHome", "OddDraw", "OddAway", "Over25", "Under25"]:
        df = df[df[c] > 1.0]
    df["season"] = np.where(df["date"].dt.month >= 7, df["date"].dt.year, df["date"].dt.year - 1)
    df = df[df["season"].isin(EXAM_SEASONS)].sort_values(["date", "Division", "HomeTeam"]).reset_index(drop=True)
    df["FTHome"] = df["FTHome"].astype(int)
    df["FTAway"] = df["FTAway"].astype(int)
    return df


def series(df, priced, groups, legs, target, label):
    recs = []
    for ids in groups:
        ids = [i for i in ids if i in priced]
        if len(ids) < legs:
            continue
        menus = [[Pick(str(i), c, priced[i]["chances"][c], priced[i]["offered"][c]) for c in priced[i]["offered"]
                  if c in SLIP_MENU and priced[i]["offered"][c] >= MIN_ODDS] for i in ids]
        slip = solve(menus, target, legs=legs, grid=0.001 if len(ids) <= 12 else 0.002, refine=False)
        if slip is None:
            continue
        won = all(settles(p.code, df.at[int(p.match_id), "FTHome"], df.at[int(p.match_id), "FTAway"]) for p in slip.picks)
        recs.append((slip.chance, slip.odds, won, snai_bonus([p.odds for p in slip.picks])))
    n = len(recs)
    exp = sum(r[0] for r in recs)
    sd = math.sqrt(sum(r[0] * (1 - r[0]) for r in recs))
    hits = sum(r[2] for r in recs)
    return {"series": label, "legs": legs, "target": target, "slips": n, "predicted_1_in": round(n / exp, 1), "expected_hits": round(exp, 2),
            "actual_hits": int(hits), "z": round((hits - exp) / sd, 2), "pass": abs(hits - exp) <= 2 * sd,
            "predicted_return_snai": round(float(np.mean([r[0] * r[1] * (1 + r[3]) for r in recs])), 3),
            "actual_return_snai": round(float(np.mean([r[1] * (1 + r[3]) if r[2] else 0 for r in recs])), 3)}


def main():
    df = load_exam()
    rows = [(i, r.OddHome, r.OddDraw, r.OddAway, r.Over25, r.Under25) for i, r in df.iterrows()]
    with ProcessPoolExecutor() as ex:
        priced = {p["idx"]: p for p in ex.map(price_match, rows, chunksize=300) if p and p["fit_error"] < 0.01}
    print(f"{len(priced)} matches, seasons {sorted(df.season.unique())}, by league {df.Division.value_counts().to_dict()}")
    result = {"matches": len(priced), "seasons": list(EXAM_SEASONS), "calibration": {}, "slips": [], "rules": []}
    ids = sorted(priced)
    verdict1 = True
    for code in sorted(SLIP_MENU | {"X", "NG"}):
        pred = np.array([priced[i]["chances"][code] for i in ids])
        won = np.array([settles(code, df.at[i, "FTHome"], df.at[i, "FTAway"]) for i in ids])
        band = (pred >= 0.55) & (pred <= 0.85)
        n = int(band.sum())
        rec = {"band_n": n, "promised": round(float(pred[band].mean()), 4) if n else None, "happened": round(float(won[band].mean()), 4) if n else None}
        if n >= 150:
            gap = abs(rec["promised"] - rec["happened"]) * 100
            limit = 2.5 if n >= 500 else 4.0
            rec["gap_points"], rec["limit"], rec["pass"] = round(gap, 2), limit, gap <= limit
            if code in SLIP_MENU and not rec["pass"]:
                verdict1 = False
        else:
            rec["pass"] = "not judged"
        result["calibration"][code] = rec
        print(code, rec)
    rounds = serie_a_rounds(df)
    pools = weekend_pools(df)
    print(f"{len(rounds)} Serie A rounds, {len(pools)} busy weekends")
    verdict2 = True
    for target in (25, 50):
        for label, groups, legs in (("Top 5 best ten", pools, 10), ("Serie A all ten", rounds, 10)):
            s = series(df, priced, groups, legs, target, label)
            result["slips"].append(s)
            verdict2 &= bool(s["pass"])
            print(s)
    for legs in (6, 8, 10):
        s = series(df, priced, pools, legs, 25, "Top 5 rules check")
        s["dev_1_in"] = DEV_1_IN[legs]
        s["within_25pct"] = abs(s["predicted_1_in"] - DEV_1_IN[legs]) <= 0.25 * DEV_1_IN[legs]
        result["rules"].append(s)
        print(s)
    result["verdict"] = {"calibration": verdict1, "slips": verdict2, "PASS": verdict1 and verdict2}
    print("VERDICT", result["verdict"])
    (OUT / "exam.json").write_text(json.dumps(result, indent=1))
    Path("docs/strategy/results").mkdir(parents=True, exist_ok=True)
    Path("docs/strategy/results/2026-09-22-slips-golive-exam-result.json").write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
