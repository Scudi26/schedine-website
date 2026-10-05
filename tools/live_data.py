"""Goal and red-card minutes from StatsBomb's open data, for the live model (decision 87).

StatsBomb (Hudl) publishes free event data for a set of competitions (github.com/statsbomb/open-data; attribution
required: "StatsBomb", with their logo where the work is published). From each match's event file this tool keeps only
what the live model needs - when each half ended, when each goal was scored and by which side, when a player was sent
off - and writes them compactly to results/live_events.json. Nothing else of the 3,000+ events per match is kept.

    python3 tools/live_data.py                       # downloads ~1,700 matches (about 5 GB read, 300 KB written; 10 min)
    python3 tools/live_data.py --limit 40            # a quick sample
    python3 tools/live_data.py --comps 12/27 2/27    # Serie A and Premier League 2015-16 only

Competitions used: full seasons of Serie A, Premier League and Ligue 1 2015-16 (the leagues Scudi bets, with Bet365
pre-match prices in the free match file), Bundesliga 2015-16 and 2023-24, La Liga 2018-21 and Ligue 1 2021-23 (one
club's matches each), the Euros 2020 and 2024, the World Cups 2018 and 2022, Copa America 2024, AFCON 2023.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "live_events.json"
BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
UA = "scudi/0.2 (personal accumulator builder; github.com/Scudi26)"
# (competition_id, season_id) -> a short label
COMPS = {(12, 27): "Serie A 2015-16", (2, 27): "Premier League 2015-16", (7, 27): "Ligue 1 2015-16", (9, 27): "Bundesliga 2015-16",
         (9, 281): "Bundesliga 2023-24", (11, 4): "La Liga 2018-19", (11, 42): "La Liga 2019-20", (11, 90): "La Liga 2020-21",
         (7, 108): "Ligue 1 2021-22", (7, 235): "Ligue 1 2022-23", (55, 43): "Euro 2020", (55, 282): "Euro 2024",
         (43, 3): "World Cup 2018", (43, 106): "World Cup 2022", (223, 282): "Copa America 2024", (1267, 107): "AFCON 2023"}
RED = {"Red Card", "Second Yellow"}


def fetch_json(url: str, tries: int = 3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # a flaky download is retried, then given up with a note
            if k == tries - 1:
                print(f"  ! {url.rsplit('/', 1)[-1]}: {e}")
                return None
            time.sleep(1 + k)


def extract(match: dict, events: list[dict]) -> dict:
    """One match's live story: half ends, goals (side, period, minute, second), red cards, final score."""
    home_id = match["home_team"]["home_team_id"]
    side = lambda ev: "h" if (ev.get("team") or {}).get("id") == home_id else "a"
    out = {"id": match["match_id"], "date": match.get("match_date"), "home": match["home_team"]["home_team_name"],
           "away": match["away_team"]["away_team_name"], "fh": match.get("home_score"), "fa": match.get("away_score"),
           "ends": {}, "goals": [], "reds": []}
    for ev in events:
        t = (ev.get("type") or {}).get("name")
        per = ev.get("period")
        if per is None or per > 4:   # 5 = penalty shoot-out
            continue
        if t == "Half End":
            out["ends"][str(per)] = [ev.get("minute"), ev.get("second")]
        elif t == "Shot" and ((ev.get("shot") or {}).get("outcome") or {}).get("name") == "Goal":
            out["goals"].append([side(ev), per, ev.get("minute"), ev.get("second"), 1 if (ev.get("shot") or {}).get("type", {}).get("name") == "Penalty" else 0])
        elif t == "Own Goal For":
            out["goals"].append([side(ev), per, ev.get("minute"), ev.get("second"), 2])
        elif t in ("Bad Behaviour", "Foul Committed"):
            card = ((ev.get("bad_behaviour") or ev.get("foul_committed") or {}).get("card") or {}).get("name")
            if card in RED:
                out["reds"].append([side(ev), per, ev.get("minute"), ev.get("second")])
    out["goals"].sort(key=lambda g: (g[1], g[2], g[3]))
    out["reds"].sort(key=lambda g: (g[1], g[2], g[3]))
    counted = (sum(1 for g in out["goals"] if g[0] == "h" and g[1] <= 4), sum(1 for g in out["goals"] if g[0] == "a" and g[1] <= 4))
    out["ok"] = counted == (out["fh"], out["fa"])   # the goals we read add up to the recorded score
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comps", nargs="*", help="competition/season ids, e.g. 12/27")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    comps = [tuple(int(x) for x in c.split("/")) for c in a.comps] if a.comps else list(COMPS)
    matches = []
    for c, s in comps:
        ms = fetch_json(f"{BASE}/matches/{c}/{s}.json") or []
        for m in ms:
            m["_label"] = COMPS.get((c, s), f"{c}/{s}")
        matches.extend(ms)
        print(f"{COMPS.get((c, s), (c, s))}: {len(ms)} matches")
    if a.limit:
        matches = matches[: a.limit]
    print(f"{len(matches)} matches to read")

    def one(m):
        ev = fetch_json(f"{BASE}/events/{m['match_id']}.json")
        if ev is None:
            return None
        rec = extract(m, ev)
        rec["comp"] = m["_label"]
        return rec
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(a.workers) as ex:
        for i, rec in enumerate(ex.map(one, matches)):
            if rec:
                rows.append(rec)
            if i % 100 == 99:
                print(f"  {i + 1} read, {time.time() - t0:.0f} s", flush=True)
    ok = sum(1 for r in rows if r["ok"])
    out = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "StatsBomb open data (github.com/statsbomb/open-data)",
           "note": "half ends, goals [side, period, minute, second, 0 shot / 1 penalty / 2 own goal], red cards [side, period, minute, second]",
           "matches": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(rows)} matches, {ok} with goals that add up, {sum(len(r['goals']) for r in rows)} goals, {sum(len(r['reds']) for r in rows)} red cards"
          f" -> {a.out} ({Path(a.out).stat().st_size // 1024} KB) in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
