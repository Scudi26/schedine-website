"""Fit the live model (decision 87): how the goal rate moves through the match, with the score and with red cards.

Data: results/live_events.json (goal and red-card minutes, half ends; tools/live_data.py, StatsBomb open data) joined to
Bet365's pre-match prices in the free match file (data/Matches.csv, football-data.co.uk via Hugging Face) for the three
full league seasons StatsBomb publishes with odds coverage: Serie A, Premier League and Ligue 1 2015-16. The pre-match
prices give each side's expected goals (margin removed, score matrix fitted as the live pipeline does); the model then
explains WHEN those goals arrive.

Model: a Poisson regression on one row per side, match and minute:
    goals in the minute ~ Poisson( lambda_side * exp(bin_m + state + cards + home) * exposure / 90 )
with 5-minute bins (plus the two stoppage-time bins), the score state at the start of the minute from that side's
view (level, one up, two or more up, one down, two or more down) and the players sent off (own side, other side). The
bin effects give the time profile of a level, eleven-a-side match; the state and card effects are multipliers on the
pre-match rate. (A home-side term was tried: 0.97 with a standard error of 0.04, i.e. nothing the pre-match expected
goals do not already carry, so it is left out and the bins are the baseline of both sides.)

    python3 tools/live_fit.py            # writes results/live_model.json (read by the site and scudi_slips/live.py)
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scudi_slips.closing import fd_key  # noqa: E402
from scudi_slips.devig import power_devig  # noqa: E402
from scudi_slips.matrix import fit_market  # noqa: E402

EVENTS = ROOT / "results" / "live_events.json"
MATCHES = ROOT / "data" / "Matches.csv"
OUT = ROOT / "results" / "live_model.json"
LEAGUES = {"Serie A 2015-16": "I1", "Premier League 2015-16": "E0", "Ligue 1 2015-16": "F1"}
BIN = 5
NBINS = 90 // BIN          # 18 regular bins
B_STOP1, B_STOP2 = NBINS, NBINS + 1
SB_ALIASES = {"internazionale": "internazionale", "inter milan": "internazionale", "ac milan": "ac milan", "milan": "ac milan", "as roma": "roma",
              "ss lazio": "lazio", "hellas verona": "verona", "chievo": "chievo", "carpi": "carpi", "frosinone": "frosinone", "sassuolo": "sassuolo",
              "west bromwich albion": "west brom", "west ham united": "west ham", "newcastle united": "newcastle", "tottenham hotspur": "tottenham",
              "manchester united": "man united", "manchester city": "man city", "leicester city": "leicester", "norwich city": "norwich",
              "stoke city": "stoke", "swansea city": "swansea", "afc bournemouth": "bournemouth", "crystal palace": "crystal palace", "paris saint germain": "paris sg",
              "olympique lyonnais": "lyon", "olympique de marseille": "marseille", "as monaco": "monaco", "ogc nice": "nice", "losc lille": "lille",
              "stade rennais": "rennes", "as saint etienne": "st etienne", "sc bastia": "bastia", "gfc ajaccio": "ajaccio gfco", "stade de reims": "reims",
              "en avant de guingamp": "guingamp", "angers sco": "angers", "fc girondins de bordeaux": "bordeaux", "montpellier hsc": "montpellier",
              "toulouse fc": "toulouse", "fc nantes": "nantes", "sm caen": "caen", "stade malherbe caen": "caen", "stade reims": "reims",
              "gazelec ajaccio": "ajaccio gfco", "fc lorient": "lorient", "estac troyes": "troyes"}


def key(name: str) -> str:
    k = fd_key(name)
    return fd_key(SB_ALIASES.get(k, k))


def load_odds() -> dict[tuple[str, str, str], tuple[float, float]]:
    """(division, date, home key) -> (lambda home, lambda away) from Bet365's pre-match prices, season 2015-16."""
    df = pd.read_csv(MATCHES, low_memory=False, usecols=["Division", "MatchDate", "HomeTeam", "AwayTeam", "OddHome", "OddDraw", "OddAway", "Over25", "Under25"])
    df = df[df.Division.isin(LEAGUES.values()) & df.MatchDate.str.startswith(("2015-", "2016-"))].dropna()
    out = {}
    for r in df.itertuples(index=False):
        try:
            ph, pd_, pa = power_devig([r.OddHome, r.OddDraw, r.OddAway])
            po, _ = power_devig([r.Over25, r.Under25])
            v = fit_market(ph, pd_, pa, po)
        except ValueError:
            continue
        if v.fit_error < 0.01:
            out[(r.Division, r.MatchDate, key(r.HomeTeam), key(r.AwayTeam))] = (v.lh, v.la)
    return out


def stoppage(m: dict) -> tuple[float, float]:
    """Stoppage time played in each half, minutes (from the half-end stamps; 0 when missing)."""
    e1, e2 = m["ends"].get("1"), m["ends"].get("2")
    s1 = max(0.0, (e1[0] + e1[1] / 60) - 45) if e1 else 0.0
    s2 = max(0.0, (e2[0] + e2[1] / 60) - 90) if e2 else 0.0
    return s1, s2


def minute_bin(period: int, minute: int) -> int:
    """StatsBomb's (period, minute) -> bin index: minute 0-44 of period 1 and 45-89 of period 2 are regular, the rest stoppage."""
    if period == 1:
        return minute // BIN if minute < 45 else B_STOP1
    return minute // BIN if minute < 90 else B_STOP2


def rows_for(m: dict, lam: tuple[float, float]) -> list[list]:
    """One row per side and minute: [y, bin, lead1, lead2, trail1, trail2, own_red, opp_red, home, exposure, log_lambda]."""
    s1, s2 = stoppage(m)
    # the clock of the match as a list of (period, minute, exposure)
    clock = [(1, k, 1.0) for k in range(45)] + [(1, 45 + k, min(1.0, s1 - k)) for k in range(math.ceil(s1))]
    clock += [(2, 45 + k, 1.0) for k in range(45)] + [(2, 90 + k, min(1.0, s2 - k)) for k in range(math.ceil(s2))]
    goals = [(g[1], g[2], g[0]) for g in m["goals"] if g[1] <= 2]
    reds = [(r[1], r[2], r[0]) for r in m["reds"] if r[1] <= 2]
    before = lambda evs, per, mi: [e for e in evs if (e[0], e[1]) < (per, mi)]
    during = lambda evs, per, mi, side: sum(1 for e in evs if e[0] == per and e[1] == mi and e[2] == side)
    out = []
    for per, mi, expo in clock:
        if expo <= 0:
            continue
        gb = before(goals, per, mi)
        rb = before(reds, per, mi)
        for side, other, lam_side, home in (("h", "a", lam[0], 1), ("a", "h", lam[1], 0)):
            diff = sum(1 for g in gb if g[2] == side) - sum(1 for g in gb if g[2] == other)
            own_red = sum(1 for r in rb if r[2] == side)
            opp_red = sum(1 for r in rb if r[2] == other)
            y = during(goals, per, mi, side)
            out.append([y, minute_bin(per, mi), int(diff == 1), int(diff >= 2), int(diff == -1), int(diff <= -2), own_red, opp_red, home, expo, math.log(lam_side)])
    return out


def poisson_glm(X: np.ndarray, y: np.ndarray, offset: np.ndarray, iters: int = 30) -> tuple[np.ndarray, np.ndarray, float]:
    """Poisson regression with a log link by iteratively reweighted least squares: coefficients, standard errors, log-likelihood."""
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = offset + X @ beta
        mu = np.exp(eta)
        z = eta - offset + (y - mu) / mu
        w = mu
        xtw = X.T * w
        new = np.linalg.solve(xtw @ X + 1e-9 * np.eye(X.shape[1]), xtw @ z)
        if np.max(np.abs(new - beta)) < 1e-9:
            beta = new
            break
        beta = new
    mu = np.exp(offset + X @ beta)
    cov = np.linalg.inv((X.T * mu) @ X)
    ll = float(np.sum(y * np.log(mu) - mu))
    return beta, np.sqrt(np.diag(cov)), ll


def profile_all(matches: list[dict]) -> dict:
    """The plain time profile on every match (no odds needed): goals per minute of play in each bin, relative to the
    average over regular time, and the average stoppage played in each half. An out-of-sample check of the fitted bins."""
    goals = Counter()
    minutes = Counter()
    stops = [stoppage(m) for m in matches]
    for m, (s1, s2) in zip(matches, stops):
        for b in range(NBINS):
            minutes[b] += BIN
        minutes[B_STOP1] += s1
        minutes[B_STOP2] += s2
        for g in m["goals"]:
            if g[1] <= 2:
                goals[minute_bin(g[1], g[2])] += 1
    reg_rate = sum(goals[b] for b in range(NBINS)) / sum(minutes[b] for b in range(NBINS))
    f = {b: (goals[b] / minutes[b]) / reg_rate if minutes[b] else None for b in range(NBINS + 2)}
    return {"f": [round(f[b], 3) for b in range(NBINS + 2)], "goals": [goals[b] for b in range(NBINS + 2)],
            "stoppage": [round(float(np.mean([s[0] for s in stops])), 2), round(float(np.mean([s[1] for s in stops])), 2)],
            "first_half_share": round(sum(goals[b] for b in [*range(9), B_STOP1]) / max(1, sum(goals.values())), 4)}


def main():
    data = json.loads(EVENTS.read_text())
    matches = [m for m in data["matches"] if m.get("ok") and m["ends"].get("1") and m["ends"].get("2")]
    odds = load_odds()
    rows, used, missing = [], [], Counter()
    for m in matches:
        div = LEAGUES.get(m["comp"])
        if not div:
            continue
        k = (div, m["date"], key(m["home"]), key(m["away"]))
        lam = odds.get(k)
        if not lam:
            missing[m["comp"]] += 1
            continue
        used.append(m)
        rows.extend(rows_for(m, lam))
    print(f"{len(matches)} matches with complete stories; {len(used)} joined to pre-match prices; unmatched by league: {dict(missing)}")
    A = np.array(rows, dtype=float)
    y = A[:, 0]
    bins = A[:, 1].astype(int)
    X = np.zeros((len(A), NBINS + 2 + 6))
    for b in range(NBINS + 2):                    # one dummy per bin and no intercept: each bin's own level, states relative
        X[:, b] = bins == b
    X[:, NBINS + 2:NBINS + 8] = A[:, 2:8]           # lead1, lead2, trail1, trail2, own_red, opp_red
    offset = A[:, 10] + np.log(A[:, 9] / 90.0)      # log(lambda * exposure / 90): a flat rate would give lambda over 90 minutes
    beta, se, ll = poisson_glm(X, y, offset)
    names = [f"bin{b}" for b in range(NBINS + 2)] + ["lead1", "lead2", "trail1", "trail2", "own_red", "opp_red"]
    coef = dict(zip(names, beta))
    # the time profile: bin multipliers scaled so that a level eleven-a-side match of expected goals lambda produces lambda
    # goals over its 90 regular minutes plus the average stoppage, at the fitted rates
    raw = np.array([math.exp(coef[f"bin{b}"]) for b in range(NBINS + 2)])
    stops = [stoppage(m) for m in used]
    stop_len = [float(np.mean([s[0] for s in stops])), float(np.mean([s[1] for s in stops]))]
    # each regular bin holds ~100-170 goals (standard error 8-10%), so the profile is smoothed with its neighbours within
    # the half (a 1-2-1 window; the first and last bin of each half with their one neighbour) before use
    sm = raw.copy()
    for lo, hi in ((0, 9), (9, NBINS)):
        for b in range(lo, hi):
            w = [(b - 1, 1.0), (b, 2.0), (b + 1, 1.0)]
            w = [(i, c) for i, c in w if lo <= i < hi]
            sm[b] = sum(raw[i] * c for i, c in w) / sum(c for _, c in w)
    total = sum(sm[b] * BIN for b in range(NBINS)) + sm[B_STOP1] * stop_len[0] + sm[B_STOP2] * stop_len[1]
    f = sm * 90.0 / total                          # now sum(f_b * len_b) = 90: the match's lambda is spread over its real length
    raw_f = raw * 90.0 / total
    check = profile_all(matches)
    out = {"fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": "StatsBomb open data (goal and red-card minutes) joined to Bet365 pre-match prices from football-data.co.uk via Hugging Face",
           "fit": {"matches": len(used), "rows": len(A), "goals": int(y.sum()), "red_cards": int(sum(len(m["reds"]) for m in used)), "loglik": round(ll, 1),
                   "leagues": sorted(LEAGUES)},
           "bin_minutes": BIN, "bins": [round(float(v), 4) for v in f[:NBINS]], "bins_unsmoothed": [round(float(v), 4) for v in raw_f[:NBINS]],
           "stoppage": {"1": {"f": round(float(f[B_STOP1]), 4), "len": round(stop_len[0], 2)}, "2": {"f": round(float(f[B_STOP2]), 4), "len": round(stop_len[1], 2)}},
           "state": {k: round(math.exp(coef[k]), 4) for k in ("lead1", "lead2", "trail1", "trail2")},
           "red": {"own": round(math.exp(coef["own_red"]), 4), "opp": round(math.exp(coef["opp_red"]), 4)},
           "se": {k: round(float(s), 4) for k, s in zip(names, se) if not k.startswith("bin")},
           "check_all_matches": {"matches": len(matches), **check}}
    # scale: at kick-off the chain must hand back the pre-match expected goals (the state multipliers above 1 would
    # otherwise add goals); one factor, fixed on typical expected-goals pairs
    from scudi_slips.live import expected_goals_at_kickoff
    out["scale"] = 1.0
    pairs = [(1.2, 1.0), (1.6, 0.9), (2.0, 0.8), (1.3, 1.3), (1.0, 1.5), (2.4, 0.7)]
    for _ in range(4):
        ratios = []
        for lh, la in pairs:
            eh, ea = expected_goals_at_kickoff(lh, la, out)
            ratios += [eh / lh, ea / la]
        out["scale"] = round(out["scale"] * float(np.mean(ratios)), 5)
    out["scale_check"] = {f"{lh}-{la}": [round(v, 4) for v in expected_goals_at_kickoff(lh, la, out)] for lh, la in pairs[:3]}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("state", "red", "stoppage", "scale")}, indent=1))
    print("profile (fitted, level 11v11):", out["bins"])
    print("profile (all matches, raw):   ", check["f"][:NBINS], "stoppage", check["f"][NBINS:], check["stoppage"], "first-half share", check["first_half_share"])
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
