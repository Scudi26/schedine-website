"""The Lab's data: three past seasons of matches with their market view and prices, for trying rules on the site.

    python3 tools/lab_data.py           # needs results/priced_markets.pkl from `python3 tools/markets.py price`

Writes lab/seasons.json (not under data/, so uploads of the code never touch it and it never changes on its own).
Per match: date, competition, teams, full-time and half-time score, the fitted score matrix (expected goals and
low-score correction) and Bet365's real result and over/under 2.5 prices. The site derives every other chance from
the matrix and every other price the way the live pipeline estimates it (decision 78). 2026-27 stays sealed.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.markets import CACHE  # noqa: E402

NAMES = {"I1": "Serie A", "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "F1": "Ligue 1", "I2": "Serie B", "E1": "Championship",
         "E2": "League One", "SP2": "La Liga 2", "D2": "2. Bundesliga", "F2": "Ligue 2", "N1": "Eredivisie", "P1": "Primeira Liga",
         "B1": "Belgian Pro League", "T1": "Süper Lig", "SC0": "Scottish Premiership", "G1": "Greek Super League"}
SEASONS = [2023, 2024, 2025]
EPOCH = date(2023, 7, 1)


def build(df: pd.DataFrame) -> dict:
    df = df[df.season.isin(SEASONS) & (df.fit_err < 0.01)].dropna(subset=["lh", "la", "rho"]).copy()
    df = df[df.Division.isin(NAMES)].sort_values(["date", "Division", "HomeTeam"])
    comps = [NAMES[d] for d in NAMES if d in set(df.Division)]
    teams = sorted(set(df.HomeTeam) | set(df.AwayTeam))
    ti = {t: i for i, t in enumerate(teams)}
    ci = {c: i for i, c in enumerate(comps)}
    rows = []
    for r in df.itertuples(index=False):
        ht = [int(r.HTHome), int(r.HTAway)] if pd.notna(r.HTHome) and pd.notna(r.HTAway) and r.HTHome <= r.FTHome and r.HTAway <= r.FTAway else [-1, -1]
        rows.append([(r.date.date() - EPOCH).days, ci[NAMES[r.Division]], ti[r.HomeTeam], ti[r.AwayTeam], int(r.FTHome), int(r.FTAway), *ht,
                     round(r.lh * 1000), round(r.la * 1000), round(r.rho * 1000),
                     round(r.OddHome * 100), round(r.OddDraw * 100), round(r.OddAway * 100), round(r.Over25 * 100), round(r.Under25 * 100)])
    return {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "epoch": EPOCH.isoformat(),
            "source": "football-data.co.uk via huggingface.co/datasets/xgabora/club-football-match-data: Bet365 pre-match prices, final and half-time scores",
            "seasons": [f"{s}-{str(s + 1)[2:]}" for s in SEASONS], "comps": comps, "teams": teams,
            "fields": ["day", "comp", "home", "away", "fh", "fa", "hh", "ha", "lh*1000", "la*1000", "rho*1000", "o1*100", "oX*100", "o2*100", "oO25*100", "oU25*100"],
            "matches": rows}


def main():
    out = build(pd.read_pickle(CACHE))
    path = ROOT / "lab" / "seasons.json"
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(out['matches'])} matches, {len(out['teams'])} teams, {len(out['comps'])} competitions -> {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
