"""Team style over the years (decision 88): one line per team and season since 2005-06, for the match drawer and the team
page - points, goals, shots, shots on target, corners, fouls, cards, home and away form, Elo, and this season's expected
goals (football-data.co.uk publishes xG per match from 2026-27).

    python3 tools/style_data.py                 # data/Matches.csv (free, Hugging Face copy of football-data.co.uk) + this season's CSVs
    python3 tools/style_data.py --offline       # history only, no download of the current season

Writes lab/style.json (not under data/, uploaded with the site like lab/seasons.json). Team names are football-data.co.uk's
(the page maps them to ESPN's with the same aliases it uses for the Lab). Shots data: the big five from 2005-06 (England
and Germany from 2000-01), the second divisions and the other European leagues from 2017-18.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scudi_slips.closing import DIVISIONS, ClosingSource, season_code  # noqa: E402
from tools.lab_data import NAMES  # noqa: E402

MATCHES = ROOT / "data" / "Matches.csv"
OUT = ROOT / "lab" / "style.json"
FIRST_SEASON = 2005
COLS = ["Division", "MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HomeShots", "AwayShots", "HomeTarget", "AwayTarget", "HomeCorners", "AwayCorners",
        "HomeFouls", "AwayFouls", "HomeYellow", "AwayYellow", "HomeRed", "AwayRed", "HomeElo", "AwayElo"]
FIELDS = ["season", "comp", "team", "p", "w", "d", "l", "gf", "ga", "shf", "sha", "sotf", "sota", "corf", "cora", "fof", "foa", "yel", "red",
          "xgf*100", "xga*100", "pts_home", "p_home", "pts_away", "p_away", "elo"]


def history() -> pd.DataFrame:
    df = pd.read_csv(MATCHES, low_memory=False, usecols=COLS)
    df = df[df.Division.isin(NAMES)].copy()
    df["date"] = pd.to_datetime(df.MatchDate, errors="coerce")
    df = df.dropna(subset=["date", "FTHome", "FTAway"])
    df["season"] = np.where(df.date.dt.month >= 7, df.date.dt.year, df.date.dt.year - 1)
    df = df[df.season >= FIRST_SEASON]
    df["HxG"] = np.nan
    df["AxG"] = np.nan
    return df.rename(columns={"HomeShots": "HS", "AwayShots": "AS", "HomeTarget": "HST", "AwayTarget": "AST", "HomeCorners": "HC", "AwayCorners": "AC",
                              "HomeFouls": "HF", "AwayFouls": "AF", "HomeYellow": "HY", "AwayYellow": "AY", "HomeRed": "HR", "AwayRed": "AR",
                              "FTHome": "FTHG", "FTAway": "FTAG"})


def current(now: datetime) -> pd.DataFrame | None:
    """This season's matches from football-data.co.uk's own files (fresher than the Hugging Face copy, and with xG)."""
    src = ClosingSource()
    frames = []
    season = int("20" + season_code(now)[:2])
    for comp, div in DIVISIONS.items():
        rows = src.rows(comp, now)
        if not rows:
            continue
        d = pd.DataFrame(rows)
        keep = [c for c in ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR", "HxG", "AxG"] if c in d.columns]
        d = d[keep].copy()
        d["Division"] = div
        d["date"] = pd.to_datetime(d["Date"], format="%d/%m/%Y", errors="coerce")
        d["season"] = season
        for c in ["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR", "HxG", "AxG"]:
            d[c] = pd.to_numeric(d[c], errors="coerce") if c in d.columns else np.nan
        d["HomeElo"] = np.nan
        d["AwayElo"] = np.nan
        frames.append(d.dropna(subset=["date", "FTHG", "FTAG"]))
    for n in src.notes:
        print("  " + n)
    return pd.concat(frames, ignore_index=True) if frames else None


def _averager(x: pd.DataFrame, p: int):
    """Per-match average of a column, or -1 when fewer than half the matches (and at least 3) carry it."""
    def avg(c: str):
        return round(float(x[c].mean()), 2) if x[c].notna().sum() >= max(3, p // 2) else -1
    return avg


def season_lines(df: pd.DataFrame) -> tuple[list[list], dict]:
    """One line per (season, division, team), and the league averages per (season, division) for the page's comparisons."""
    recs = []
    for r in df.itertuples(index=False):
        for side, team in (("h", r.HomeTeam), ("a", r.AwayTeam)):
            home = side == "h"
            gf, ga = (r.FTHG, r.FTAG) if home else (r.FTAG, r.FTHG)
            pts = 3 if gf > ga else 1 if gf == ga else 0
            recs.append({"season": int(r.season), "comp": r.Division, "team": team, "home": home, "gf": gf, "ga": ga, "pts": pts,
                         "shf": r.HS if home else r.AS, "sha": r.AS if home else r.HS, "sotf": r.HST if home else r.AST, "sota": r.AST if home else r.HST,
                         "corf": r.HC if home else r.AC, "cora": r.AC if home else r.HC, "fof": r.HF if home else r.AF, "foa": r.AF if home else r.HF,
                         "yel": r.HY if home else r.AY, "red": r.HR if home else r.AR, "xgf": r.HxG if home else r.AxG, "xga": r.AxG if home else r.HxG,
                         "elo": r.HomeElo if home else r.AwayElo, "date": r.date})
    t = pd.DataFrame(recs)
    g = t.groupby(["season", "comp", "team"], sort=True)
    out = []
    means = {}
    for (season, comp, team), x in g:
        p = len(x)
        w = int((x.gf > x.ga).sum())
        d = int((x.gf == x.ga).sum())
        avg = _averager(x, p)
        hm, aw = x[x.home], x[~x.home]
        elo = x.sort_values("date").elo.dropna()
        out.append([season, comp, team, p, w, d, p - w - d, int(x.gf.sum()), int(x.ga.sum()), avg("shf"), avg("sha"), avg("sotf"), avg("sota"), avg("corf"), avg("cora"),
                    avg("fof"), avg("foa"), avg("yel"), avg("red"), round(100 * x.xgf.mean()) if x.xgf.notna().sum() >= 3 else -1, round(100 * x.xga.mean()) if x.xga.notna().sum() >= 3 else -1,
                    int(hm.pts.sum()), len(hm), int(aw.pts.sum()), len(aw), round(elo.iloc[-1]) if len(elo) else -1])
    for (season, comp), x in t.groupby(["season", "comp"]):
        means[f"{season}|{comp}"] = [round(float(x[c].mean()), 2) if x[c].notna().any() else -1 for c in ("shf", "sotf", "corf", "gf", "xgf")]
    return out, means


def build(df: pd.DataFrame) -> dict:
    lines, means = season_lines(df)
    comps = sorted({ln[1] for ln in lines}, key=lambda d: list(NAMES).index(d))
    teams = sorted({ln[2] for ln in lines})
    seasons = sorted({ln[0] for ln in lines})
    ci, ti, si = {c: i for i, c in enumerate(comps)}, {t: i for i, t in enumerate(teams)}, {s: i for i, s in enumerate(seasons)}
    rows = [[si[ln[0]], ci[ln[1]], ti[ln[2]], *[v if isinstance(v, int) else (int(v) if float(v).is_integer() else v) for v in ln[3:]]] for ln in lines]
    return {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "football-data.co.uk (results, shots, corners, cards; xG from 2026-27) via its Hugging Face copy for past seasons and its own files for this one",
            "seasons": [f"{s}-{str(s + 1)[2:]}" for s in seasons], "comps": [NAMES[c] for c in comps], "divisions": comps, "teams": teams,
            "fields": FIELDS, "rows": rows,
            "league": {f"{si[int(k.split('|')[0])]}|{ci[k.split('|')[1]]}": v for k, v in means.items() if k.split("|")[1] in ci}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    df = history()
    cur = None if a.offline else current(now)
    if cur is not None and len(cur):
        season = int(cur.season.iloc[0])
        df = pd.concat([df[df.season != season], cur[df.columns.intersection(cur.columns)]], ignore_index=True)
        print(f"this season from football-data.co.uk: {len(cur)} matches in {cur.Division.nunique()} divisions, xG on {int(cur.HxG.notna().sum())}")
    out = build(df)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(out['rows'])} team-seasons, {len(out['teams'])} teams, {len(out['comps'])} competitions, {out['seasons'][0]} -> {out['seasons'][-1]} -> {a.out} ({Path(a.out).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
