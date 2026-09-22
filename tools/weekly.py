"""The weekly job: pull this week's prices, price every match, build the preset slips, write the site's data file.

    ODDS_API_KEY=... python3 -m tools.weekly --mode auto              # what the workflow runs every morning
    python3 -m tools.weekly --mode full --window-days 6 --out data/week.json
    python3 -m tools.weekly --from-file tests/feed_sample.json --now 2026-10-09T10:00:00Z   (no network: replay a recorded feed)

Modes (decision 73):
  full  pull every competition, price the window, build the preset slips (the ones that get graded). Friday and Tuesday.
  late  a match-day refresh: only the competitions with a kickoff in the next `late_hours`; their upcoming matches get
        fresher prices, matches that have kicked off keep their last prices, the preset slips are left as they were.
        Nothing due = no call, no credit spent. Every other morning.
  auto  full on Friday and Tuesday (UTC), late otherwise.
Every pull also appends a snapshot of each match's chances and estimated prices to data/history.json, which the
site draws as price movement and the grading job uses as the closing chance of each leg.

Credits: 2 per competition per pull on the free plan (h2h + totals, one region). A full pull of six competitions is 12
credits; a match-day pull 2-10. The job prints the remaining monthly credits from the response headers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, snai_bonus, solve
from scudi_slips.feed import SPORT_KEYS, price_feed

API = "https://api.the-odds-api.com/v4/sports/{key}/odds"
DEFAULT_COMPS = ["Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1", "Champions League"]
TOP5 = DEFAULT_COMPS[:5]
MIN_ODDS = 1.25
TARGETS = [25, 30, 40, 50]


def fetch(comps: list[str], api_key: str, region: str = "eu") -> tuple[dict[str, list], dict[str, str]]:
    events, meta = {}, {}
    for comp in comps:
        q = urllib.parse.urlencode({"apiKey": api_key, "regions": region, "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso"})
        req = urllib.request.Request(API.format(key=SPORT_KEYS[comp]) + "?" + q, headers={"User-Agent": "scudi/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            events[comp] = json.loads(r.read().decode("utf-8"))
            meta = {"remaining": r.headers.get("x-requests-remaining"), "used": r.headers.get("x-requests-used")}
    return events, meta


def preset_slips(matches, now: datetime) -> list[dict]:
    """The four standing slips, at every target, from what the feed allows; each is recorded so it can be graded later."""
    by_comp: dict[str, list] = {}
    for m in matches:
        by_comp.setdefault(m.competition, []).append(m)
    ucl = sorted(by_comp.get("Champions League", []), key=lambda m: m.kickoff)
    days = sorted({m.kickoff.date() for m in ucl})
    presets = [("Serie A", by_comp.get("Serie A", []), 10), ("Top 5 leagues", [m for c in TOP5 for m in by_comp.get(c, [])], 10)]
    for d in days[:2]:
        presets.append((f"Champions League {d.strftime('%a')}", [m for m in ucl if m.kickoff.date() == d], 9))
    out = []
    for name, pool, legs in presets:
        legs = min(legs, len(pool))
        if legs < 5:
            continue
        menus = [[Pick(m.id, c, m.chances[c], m.estimate[c]) for c in m.estimate if c in SLIP_MENU and c in m.chances and m.estimate[c] >= MIN_ODDS] for m in pool]
        for t in TARGETS:
            slip = solve(menus, t, legs=legs, grid=0.001 if len(pool) <= 12 else 0.002)
            if slip is None:
                continue
            out.append({"name": name, "target": t, "legs": legs, "built_at": now.isoformat(), "chance": slip.chance, "odds": slip.odds,
                        "bonus": snai_bonus([p.odds for p in slip.picks]),
                        "picks": [{"match": p.match_id, "code": p.code, "chance": p.chance, "odds": p.odds} for p in slip.picks]})
    return out


def match_record(m) -> dict:
    return {"id": m.id, "competition": m.competition, "kickoff": m.kickoff.isoformat(), "home": m.home, "away": m.away,
            "chances": {k: round(v, 5) for k, v in m.chances.items()}, "estimate": m.estimate,
            "best": {k: [b, p] for k, (b, p) in m.best.items()}, "books_used": m.books_used, "sharp_share": round(m.sharp_share, 3),
            "lh": round(m.lh, 4), "la": round(m.la, 4)}


HISTORY_CODES = ("1", "X", "2", "1X", "X2", "12", "O15", "O25", "U25", "U35", "GG")


def add_snapshots(history: dict, matches: list[dict], now: datetime, keep_days: float = 10.0) -> dict:
    """Append one snapshot per match (chances and estimated prices) and drop matches that ended long ago."""
    for m in matches:
        if datetime.fromisoformat(m["kickoff"]) <= now:
            continue   # a started match keeps the snapshots it had: the last one is its closing view
        h = history.setdefault(m["id"], {"home": m["home"], "away": m["away"], "competition": m["competition"], "kickoff": m["kickoff"], "snaps": []})
        h["kickoff"] = m["kickoff"]
        snap = {"t": now.isoformat(), "p": {k: round(v, 4) for k, v in m["chances"].items() if k in HISTORY_CODES},
                "o": {k: v for k, v in m["estimate"].items() if k in HISTORY_CODES}}
        if h["snaps"] and h["snaps"][-1]["t"] == snap["t"]:
            h["snaps"][-1] = snap
        else:
            h["snaps"].append(snap)
    cutoff = now - timedelta(days=keep_days)
    return {k: v for k, v in history.items() if datetime.fromisoformat(v["kickoff"]) >= cutoff}


def closing(history: dict, match_id: str) -> dict | None:
    """The last snapshot taken before kickoff: the closest thing to the closing price the free feed allows."""
    h = history.get(match_id)
    if not h or not h["snaps"]:
        return None
    ko = h["kickoff"]
    before = [s for s in h["snaps"] if s["t"] < ko]
    return (before or h["snaps"])[-1]


def comps_due(week: dict, now: datetime, hours: float) -> list[str]:
    """Competitions with at least one kickoff in the next `hours`: the only ones a match-day pull refreshes."""
    end = now + timedelta(hours=hours)
    return sorted({m["competition"] for m in week.get("matches", []) if now < datetime.fromisoformat(m["kickoff"]) <= end})


def merge_late(old: dict, fresh: list[dict], refreshed: list[str], now: datetime) -> dict:
    """Fresh prices replace old ones for upcoming matches of the refreshed competitions; everything else is kept as it was
    (matches that kicked off keep their last pre-kickoff prices, other competitions are untouched, slips are untouched)."""
    new_by_id = {m["id"]: m for m in fresh}
    out, seen = [], set()
    for m in old.get("matches", []):
        if m["competition"] in refreshed and m["id"] in new_by_id:
            out.append(new_by_id[m["id"]])
        else:
            out.append(m)
        seen.add(m["id"])
    out += [m for m in fresh if m["id"] not in seen]   # a match the feed listed late
    out.sort(key=lambda m: (m["kickoff"], m["competition"], m["home"]))
    data = dict(old)
    data.update({"matches": out, "refreshed_at": now.isoformat(), "refreshed": refreshed})
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comps", nargs="*", default=DEFAULT_COMPS)
    ap.add_argument("--mode", choices=["full", "late", "auto"], default="full")
    ap.add_argument("--late-hours", type=float, default=18.0, help="late mode: refresh competitions with a kickoff this soon")
    ap.add_argument("--window-days", type=float, default=6.0)
    ap.add_argument("--from-file", help="replay a recorded feed instead of calling the API")
    ap.add_argument("--now", help="pretend it is this UTC time (ISO), for replays")
    ap.add_argument("--out", default="data/week.json")
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--need-sharp", action="store_true", help="drop matches with no Pinnacle/Betfair price")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    out, hist_path = Path(a.out), Path(a.history)
    old = json.loads(out.read_text()) if out.exists() else {}
    mode = a.mode
    if mode == "auto":
        mode = "full" if now.weekday() in (1, 4) or not old.get("matches") else "late"
    comps = a.comps
    if mode == "late":
        comps = comps_due(old, now, a.late_hours)
        if not comps:
            print(f"late pull: no kickoff in the next {a.late_hours:g} hours, nothing fetched, no credit spent")
            return 0
    if a.from_file:
        events, meta = json.loads(Path(a.from_file).read_text()), {}
        events = {c: v for c, v in events.items() if c in comps}
    else:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            sys.exit("ODDS_API_KEY is not set (keep it in a GitHub secret or a password manager, never in the code)")
        events, meta = fetch(comps, key)
    window = float(old.get("window_days", a.window_days)) if mode == "late" else a.window_days
    matches, guard = price_feed(events, now, now + timedelta(days=window), need_sharp=a.need_sharp)
    fresh = [match_record(m) for m in matches]
    if mode == "late":
        data = merge_late(old, fresh, comps, now)
        data["credits"] = meta or data.get("credits", {})
        note = f"late pull of {', '.join(comps)}: {len(fresh)} upcoming matches refreshed, preset slips unchanged"
    else:
        slips = preset_slips(matches, now)
        data = {"built_at": now.isoformat(), "window_days": a.window_days, "credits": meta, "guard": guard.__dict__, "matches": fresh, "slips": slips}
        note = f"{guard.kept} matches priced, {len(slips)} preset slips built"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    history = add_snapshots(history, fresh, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    hist_path.write_text(json.dumps(history, separators=(",", ":")))
    print(f"{note} -> {out}; history: {len(history)} matches; guard: {guard.__dict__}; credits: {meta}")
    return 0


if __name__ == "__main__":
    main()
