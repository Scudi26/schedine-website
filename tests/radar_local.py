"""Local stand-in for the Radar screen (decision 99): a throwaway Postgres with every migration, filled with a simulated
stretch of the price memory, served on 127.0.0.1:54321 with the same endpoints, roles and row-level security as
Supabase (tests/feed_local.py's server), so the site can be opened signed in and the page drawn on known numbers.

    python3 tests/radar_local.py --pg /var/lib/postgresql/scudi --days 28       # four weeks of matches in 11 leagues
    python3 tests/radar_local.py --pg … --days 1                                 # one evening: thin data
    python3 tests/radar_local.py --pg … --days 0                                 # nothing finished yet
    python3 tests/radar_local.py --pg … --days 28 --check                        # print the page call's headline and stop

The matches are invented, but their numbers follow one score model each (Dixon–Coles, the site's matrix): Pinnacle's
close is that model at a 2.5% margin, SNAI's prices carry a margin by market, price level and league that drifts in
the hours before kick-off, and the final scores are drawn from the same model — so the calibration chart should sit on
its diagonal and the margin map should show the margins put in (SNAI's 1X2 ≈ −5%, goals ≈ −8%, long shots dearer).
Then the site: serve the folder (python3 -m http.server 8765), open it with window.SCUDI_FEED_CONF =
{url: 'http://127.0.0.1:54321', key: 'sb_publishable_localtest'} and sign in as gianluca@example.com / pw-owner.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feed_local as fl

LEAGUES = [("Serie A", -0.006), ("Premier League", -0.004), ("LaLiga", 0.0), ("Bundesliga", 0.002), ("Ligue 1", 0.004), ("Serie B", 0.008),
           ("Championship", 0.006), ("League One", 0.014), ("LaLiga 2", 0.010), ("2. Bundesliga", 0.009), ("Ligue 2", 0.012)]
MARGIN = {1: 0.052, 2: 0.060, 3: 0.080, 4: 0.082}   # SNAI's overround-like cost by market (decision 71's medians)
READ_H = [60, 40, 30, 20, 12, 8, 5, 3, 2, 1, 0.5, 0.13]   # hours before kick-off when SNAI and the sharp books are read


def matrix(lh: float, la: float, rho: float = -0.05) -> dict[int, float]:
    """the site's Dixon–Coles matrix 0..9 → the memory's selections (no +1.5 points on GG: this is the 'true' model)"""
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(10)]
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(10)]
    g = {}
    for i in range(10):
        for j in range(10):
            v = ph[i] * pa[j]
            if i == 0 and j == 0:
                v *= 1 - lh * la * rho
            elif i == 0 and j == 1:
                v *= 1 + lh * rho
            elif i == 1 and j == 0:
                v *= 1 + la * rho
            elif i == 1 and j == 1:
                v *= 1 - rho
            g[(i, j)] = v
    t = sum(g.values())
    g = {k: v / t for k, v in g.items()}
    s = lambda f: sum(v for (i, j), v in g.items() if f(i, j))
    hw, dr, aw = s(lambda i, j: i > j), s(lambda i, j: i == j), s(lambda i, j: i < j)
    o15, o25, o35, bt = s(lambda i, j: i + j >= 2), s(lambda i, j: i + j >= 3), s(lambda i, j: i + j >= 4), s(lambda i, j: i > 0 and j > 0)
    return {100001: hw, 100002: dr, 100003: aw, 200001: hw + dr, 200002: hw + aw, 200003: dr + aw, 301501: 1 - o15, 301502: o15,
            302501: 1 - o25, 302502: o25, 303501: 1 - o35, 303502: o35, 400001: bt, 400002: 1 - bt, "grid": g}


def market(code: int) -> int:
    return code // 100000


def build(dsn: str, days: float, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    events, ticks, fits, results = [], [], [], []
    # finished matches over the window (about 100 a week in the 11 leagues), plus tomorrow's (not finished: no grade)
    n_done = round(days * 14.5)
    kicks = sorted(now - timedelta(hours=rnd.uniform(2.2, max(2.3, days * 24))) for _ in range(n_done))
    kicks += [now + timedelta(hours=rnd.uniform(3, 40)) for _ in range(12)]
    for n, k in enumerate(kicks):
        lg, lgm = LEAGUES[n % len(LEAGUES)]
        eid, mid = f"R{n}", f"mr{n}"
        lh, la = rnd.uniform(0.8, 2.2), rnd.uniform(0.6, 1.8)
        close = matrix(lh, la)
        closed = rnd.random() < 0.97
        events.append({"event_id": eid, "home": f"Home {n}", "away": f"Away {n}", "league": lg, "commence_time": k.isoformat(), "match_id": mid,
                       "near_at": (k - timedelta(minutes=8) if closed else k - timedelta(hours=3)).isoformat(), "near_books": ["snai", "pinnacle", "betfair_ex_eu"]})
        drift = {c: rnd.gauss(0, 0.025) for c in close if c != "grid"}
        for h in READ_H:
            if not closed and h < 3:
                continue
            at = k - timedelta(hours=h)
            if at > now:
                continue
            w = min(1.0, h / 48)   # the price as it stood then: further from the close the earlier it was
            fair = {c: min(0.97, max(0.03, p * (1 + drift[c] * w))) for c, p in close.items() if c != "grid"}
            snai_c, snai_p = [], []
            for c, p in fair.items():
                m = MARGIN[market(c)] + lgm + (0.03 if p < 0.3 else 0.012 if p < 0.45 else 0) + (0.012 if c == 100002 else 0)
                m += -0.006 * w   # SNAI a little cheaper early (it moves late)
                if market(c) == 3 and c // 10 % 10000 not in (150, 250, 350):
                    continue
                if lg == "Serie A" and c in (100001, 100003) and p > 0.55:
                    m -= 0.04   # a cheap pocket on purpose: Serie A's favourites to win
                snai_c.append(c)
                snai_p.append(round(max(1.01, 1 / (p * (1 + m)) * math.exp(rnd.gauss(0, 0.03))), 2))   # SNAI's own pricing noise
            ticks.append({"event_id": eid, "book": "snai", "at": at.isoformat(), "c": snai_c, "p": snai_p})
            pin = [100001, 100002, 100003, 301501, 301502, 302501, 302502, 303501, 303502]
            ticks.append({"event_id": eid, "book": "pinnacle", "at": (at + timedelta(seconds=5)).isoformat(), "c": pin, "p": [round(1 / (fair[c] * 1.025), 3) for c in pin]})
            ticks.append({"event_id": eid, "book": "betfair_ex_eu", "at": (at + timedelta(seconds=6)).isoformat(), "c": [400001, 400002], "p": [round(1 / (fair[c] * 1.01), 2) for c in (400001, 400002)]})
        fits.append({"event_id": eid, "at": (k - timedelta(hours=1)).isoformat(), "p": [close[100001], close[100002], close[100003], close[302502]], "lh": lh, "la": la, "rho": -0.05})
        if k < now - timedelta(hours=2):   # the result, drawn from the same model
            cells, wts = zip(*close["grid"].items())
            hg, ag = rnd.choices(cells, weights=wts)[0]
            results.append((mid, hg, ag))
    with fl.psycopg.connect(dsn, autocommit=True) as c:
        c.execute("delete from public.memory_events")
        c.execute("delete from public.match_results")
        with c.cursor() as cur:
            cur.executemany("insert into public.memory_events (event_id, home, away, league, commence_time, match_id, near_at, near_books) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                            [(e["event_id"], e["home"], e["away"], e["league"], e["commence_time"], e["match_id"], e["near_at"], e["near_books"]) for e in events])
            cur.executemany("insert into public.price_ticks (event_id, book, at, c, p) values (%s, %s, %s, %s, %s) on conflict do nothing",
                            [(t["event_id"], t["book"], t["at"], t["c"], t["p"]) for t in ticks])
            cur.executemany("insert into public.fit_ticks (event_id, at, p, lh, la, rho, err, sharp, nb, tier) values (%s, %s, %s, %s, %s, %s, 0, 1, 4, 'ref')",
                            [(f["event_id"], f["at"], f["p"], f["lh"], f["la"], f["rho"]) for f in fits])
            cur.executemany("insert into public.match_results (match_id, ft_h, ft_a) values (%s, %s, %s)", results)
            cur.execute("insert into public.feed_log (kind, requests, status, note) values ('closing', 1, 200, 'radar stand-in')")
        c.execute("analyze")
    return {"events": len(events), "finished": n_done, "ticks": len(ticks), "results": len(results)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True, help="Postgres socket directory (port 55432)")
    ap.add_argument("--days", type=float, default=28, help="days of finished matches (0 = none yet)")
    ap.add_argument("--check", action="store_true", help="print the page call's headline numbers and stop")
    a = ap.parse_args()
    fl.fresh_db(a.pg)
    info = build(fl.STATE["dsn"], a.days)
    print("built:", json.dumps(info), flush=True)
    if a.check:
        j = fl.run_as("authenticated", fl.USERS["gianluca@example.com"][0], "select public.radar_page(28)")[0][0]
        heads = [g for g in j["groups"] if g[0] in ("a", "m") and g[1] == 0]
        print(json.dumps({"health": j["health"], "heads": heads, "calib": j["calib"], "sources": j["sources"]}, indent=1))
        return 0
    srv = ThreadingHTTPServer(("127.0.0.1", fl.PORT), fl.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("serving on 127.0.0.1:54321 — Ctrl+C to stop", flush=True)
    try:
        while True:
            time.sleep(3600)
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
