"""The weekly job: pull this week's prices, price every match, build the preset slips, write the site's data file.

    ODDS_API_KEY=... python3 -m tools.weekly --window-days 6 --out data/week.json
    python3 -m tools.weekly --from-file tests/feed_sample.json --now 2026-10-09T10:00:00Z   (no network: replay a recorded feed)

Credits: 2 per competition per pull on the free plan (h2h + totals, one region). Six competitions = 12 credits;
with the five second divisions 22. The job prints the remaining monthly credits from the response headers.
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comps", nargs="*", default=DEFAULT_COMPS)
    ap.add_argument("--window-days", type=float, default=6.0)
    ap.add_argument("--from-file", help="replay a recorded feed instead of calling the API")
    ap.add_argument("--now", help="pretend it is this UTC time (ISO), for replays")
    ap.add_argument("--out", default="data/week.json")
    ap.add_argument("--need-sharp", action="store_true", help="drop matches with no Pinnacle/Betfair price")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    if a.from_file:
        events, meta = json.loads(Path(a.from_file).read_text()), {}
    else:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            sys.exit("ODDS_API_KEY is not set (keep it in a GitHub secret or a password manager, never in the code)")
        events, meta = fetch(a.comps, key)
    matches, guard = price_feed(events, now, now + timedelta(days=a.window_days), need_sharp=a.need_sharp)
    slips = preset_slips(matches, now)
    data = {
        "built_at": now.isoformat(), "window_days": a.window_days, "credits": meta, "guard": guard.__dict__,
        "matches": [{"id": m.id, "competition": m.competition, "kickoff": m.kickoff.isoformat(), "home": m.home, "away": m.away,
                     "chances": {k: round(v, 5) for k, v in m.chances.items()}, "estimate": m.estimate,
                     "best": {k: [b, p] for k, (b, p) in m.best.items()}, "books_used": m.books_used, "sharp_share": round(m.sharp_share, 3),
                     "lh": round(m.lh, 4), "la": round(m.la, 4)}
                    for m in matches],
        "slips": slips,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    print(f"{guard.kept} matches priced, {len(slips)} preset slips built -> {out}; guard: {guard.__dict__}; credits: {meta}")


if __name__ == "__main__":
    main()
