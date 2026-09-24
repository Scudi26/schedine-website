"""The new pick types (multigol, team goals, combos, 1X2 handicap, first half) on 21 seasons of real results.

    python3 tools/markets.py price     # Bet365 prices -> score matrix for every match (~3 min on 2 cores), cache in results/
    python3 tools/markets.py fit       # first-half model + calibration corrections, fit seasons only
    python3 tools/markets.py check     # the check seasons (2017-18 .. 2023-24)
    python3 tools/markets.py confirm   # the confirm seasons (2024-25, 2025-26): run once, pre-registered

Data: huggingface.co/datasets/xgabora/club-football-match-data (built from football-data.co.uk), file data/Matches.csv
(45 MB, not stored). 17 divisions: the big five, their second divisions, League One, Eredivisie, Primeira Liga, Belgium,
Turkey, Scotland, Greece. Chances: Bet365 result and over/under 2.5 prices, margin removed (power), fitted to the score
matrix exactly as the live site does. Pre-registration and pass marks: docs/strategy/2026-09-23-new-markets.md.
Result (decision 78): results/markets.json.
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import fit_market, power_devig
from scudi_slips.matrix import HALF_RHO, HALF_SHARE, MAX_GOALS
from scudi_slips.picks import BTTS_SHIFT, CORR, MASKS, NOT_OFFERED, PICKS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "Matches.csv"
CACHE = ROOT / "results" / "priced_markets.pkl"   # not stored (23 MB)
DIVS = ["I1", "E0", "SP1", "D1", "F1", "I2", "E1", "E2", "SP2", "D2", "F2", "N1", "P1", "B1", "T1", "SC0", "G1"]
BANDS = (("mid", 0.30, 0.55), ("slip", 0.55, 0.85), ("high", 0.85, 0.97))
K = np.arange(MAX_GOALS)
FACT = np.array([math.factorial(i) for i in K], float)


def part_of(season):
    return np.where(season <= 2016, "fit", np.where(season <= 2023, "check", np.where(season <= 2025, "confirm", "sealed")))


def _price(row):
    oh, od, oa, oo, ou = row
    try:
        ph, pd_, pa = power_devig([oh, od, oa])
        po, _ = power_devig([oo, ou])
        v = fit_market(ph, pd_, pa, po)
        return (v.lh, v.la, v.rho, v.fit_error, ph, pd_, pa, po)
    except ValueError:
        return (np.nan,) * 8


def price():
    df = pd.read_csv(DATA, low_memory=False)
    df = df[df.Division.isin(DIVS)].copy()
    df["date"] = pd.to_datetime(df.MatchDate, errors="coerce")
    df = df.dropna(subset=["date", "FTHome", "FTAway", "OddHome", "OddDraw", "OddAway", "Over25", "Under25"])
    for c in ["OddHome", "OddDraw", "OddAway", "Over25", "Under25"]:
        df = df[df[c] > 1.0]
    df["season"] = np.where(df.date.dt.month >= 7, df.date.dt.year, df.date.dt.year - 1)
    df = df[df.season >= 2005].sort_values(["date", "Division", "HomeTeam"]).reset_index(drop=True)
    rows = list(df[["OddHome", "OddDraw", "OddAway", "Over25", "Under25"]].itertuples(index=False, name=None))
    with ProcessPoolExecutor(2) as ex:
        res = np.array(list(ex.map(_price, rows, chunksize=500)), dtype=float)
    for i, c in enumerate(["lh", "la", "rho", "fit_err", "ph", "pd", "pa", "po"]):
        df[c] = res[:, i]
    df.to_pickle(CACHE)
    print(f"priced {len(df)} matches -> {CACHE}")


def batch_matrix(lh, la, rho):
    """Dixon–Coles matrices for many matches at once (n, 10, 10), the same maths as matrix.score_matrix."""
    lh, la = lh[:, None], la[:, None]
    m = (np.exp(-lh) * lh ** K / FACT)[:, :, None] * (np.exp(-la) * la ** K / FACT)[:, None, :]
    hi = np.minimum(1.0 / (lh[:, 0] * la[:, 0]), 1.0) * 0.999
    lo = -np.minimum(1.0 / lh[:, 0], 1.0 / la[:, 0]) * 0.999
    r = np.clip(rho, lo, hi)
    m[:, 0, 0] *= 1 - lh[:, 0] * la[:, 0] * r
    m[:, 0, 1] *= 1 + lh[:, 0] * r
    m[:, 1, 0] *= 1 + la[:, 0] * r
    m[:, 1, 1] *= 1 - r
    return m / m.sum(axis=(1, 2), keepdims=True)


def load():
    df = pd.read_pickle(CACHE)
    df = df[df.fit_err < 0.01].dropna(subset=["lh", "la", "rho", "HTHome", "HTAway"]).copy()
    df = df[(df.HTHome <= df.FTHome) & (df.HTAway <= df.FTAway)]
    df["part"] = part_of(df.season.values)
    return df


def lg(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sg(x):
    return 1 / (1 + np.exp(-x))


def chances(df, share=HALF_SHARE, rho_half=HALF_RHO, corr=CORR):
    """Chance and outcome of every pick type for every match, as the site computes them."""
    ft = batch_matrix(df.lh.values, df.la.values, df.rho.values)
    ht = batch_matrix(df.lh.values * share, df.la.values * share, np.full(len(df), rho_half))
    fh, fa, hh, ha = (df[c].values.astype(int) for c in ("FTHome", "FTAway", "HTHome", "HTAway"))
    raw, won = {}, {}
    for code, pt in PICKS.items():
        p = (ht if pt.half else ft)[:, MASKS[code]].sum(axis=1)
        raw[code] = np.minimum(0.99, p + BTTS_SHIFT) if code == "GG" else p
        won[code] = np.array([pt.wins(x, y) for x, y in (zip(hh, ha) if pt.half else zip(fh, fa))])
    out = {}
    for code, pt in PICKS.items():
        p = raw[code]
        if code in corr:
            a, b = corr[code]
            p = sg(a + b * lg(p))
            if pt.parts:
                ps = [raw[x] if x not in corr else sg(corr[x][0] + corr[x][1] * lg(raw[x])) for x in pt.parts]
                p = np.minimum(p, np.minimum(*ps))
        out[code] = p
    return out, won, raw


def fit():
    df = load()
    f = df[df.part == "fit"]

    def nll(params):
        s, rh = params
        m = batch_matrix(f.lh.values * s, f.la.values * s, np.full(len(f), rh))
        hh, ha = f.HTHome.values.astype(int).clip(0, MAX_GOALS - 1), f.HTAway.values.astype(int).clip(0, MAX_GOALS - 1)
        return -np.log(np.clip(m[np.arange(len(f)), hh, ha], 1e-12, 1)).sum()
    r = minimize(nll, [0.45, 0.0], method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-3})
    print(f"first half: share {r.x[0]:.4f}, low-score correction {r.x[1]:.4f} ({len(f)} matches)")
    _, won, raw = chances(f, r.x[0], r.x[1], corr={})
    corr = {}
    for code, pt in PICKS.items():
        if pt.group in ("result", "double chance", "goals", "both score"):
            continue
        x, y = lg(raw[code]), won[code].astype(float)
        def nl(ab, x=x, y=y):
            q = np.clip(sg(ab[0] + ab[1] * x), 1e-9, 1 - 1e-9)
            return -np.sum(y * np.log(q) + (1 - y) * np.log(1 - q))
        s = minimize(nl, [0.0, 1.0], method="Nelder-Mead", options={"xatol": 1e-7, "fatol": 1e-6, "maxiter": 2000})
        corr[code] = (round(float(s.x[0]), 4), round(float(s.x[1]), 4))
    print(json.dumps(corr))


def report(parts: list[str]):
    df = load()
    p, won, _ = chances(df)
    part = df.part.values
    res = json.loads((ROOT / "results" / "markets.json").read_text()) if (ROOT / "results" / "markets.json").exists() else {"codes": {}}
    for code, pt in PICKS.items():
        rec = res["codes"].setdefault(code, {"group": pt.group})
        for pn in parts:
            for band, lo, hi in BANDS:
                m = (part == pn) & (p[code] >= lo) & (p[code] < hi)
                n = int(m.sum())
                if not n:
                    continue
                pr, hp = float(p[code][m].mean()) * 100, float(won[code][m].mean()) * 100
                lim = 2.5 if n >= 500 else 4.0 if n >= 150 else None
                rec[f"{pn}_{band}"] = [n, round(pr, 2), round(hp, 2), None if lim is None else bool(abs(hp - pr) <= lim)]
        line = " | ".join(f"{k} {v[0]} {v[1]:.1f}->{v[2]:.1f}{'' if v[3] is None else (' ok' if v[3] else ' FAIL')}" for k, v in rec.items() if k.split("_")[0] in parts)
        print(f"{code:9s} {'offered' if code not in NOT_OFFERED else 'not offered':11s} {line}")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "price":
        price()
    elif cmd == "fit":
        fit()
    else:
        report({"check": ["check"], "confirm": ["confirm"], "all": ["fit", "check", "confirm"]}.get(cmd, ["check"]))
