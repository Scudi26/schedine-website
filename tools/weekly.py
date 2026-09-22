"""The price job: pull the week's prices, price every match, build the preset slips, write the site's data file.

    ODDS_API_KEY=... python3 -m tools.weekly --mode auto              # what the workflow runs every morning
    python3 -m tools.weekly --mode full --out data/week.json
    python3 -m tools.weekly --from-file tests/feed_sample.json --now 2026-10-09T10:00:00Z   (no network: replay a recorded feed)

Modes (decisions 73, 74):
  full  pull every competition in season, price the window, build the preset slips (the ones that get graded).
        Friday and Tuesday, or any morning the stored week has no match at all.
  late  a match-day refresh: only the core and national-team competitions with a kickoff in the next `late_hours`;
        their upcoming matches get fresher prices, the rest is kept as it was. Nothing due = no call, no credit spent.
  auto  full on Friday and Tuesday (UTC) or while the stored week is empty (an international break), late otherwise.

The window: a full pull covers kickoffs up to the next Tuesday or Friday 06:00 UTC at least 12 hours away (Friday's
pull covers the weekend and Monday, Tuesday's the midweek), so no match is paid for twice in the same week. One
exception: the weekend pull looks six days ahead for the core competitions, so the Champions League nights (and any
midweek round of the big leagues) show from Friday, as before.

Credits (free plan, 500 a month): one odds call = 2 credits (h2h + totals, one region), and only when it returns a match
in the window: the calls carry commenceTimeFrom/commenceTimeTo, and the feed does not charge a call that returns
nothing. The sports list (which competitions are in season) is free. Core and national-team competitions are always
pulled; the cups, second divisions and other European leagues only while the credits left cover about 7 a day until the
monthly reset, so the core never runs dry. Every pull records what it spent, what it skipped and why.
Every pull also appends a snapshot of each match's chances and estimated prices to data/history.json, which the
site draws as price movement and the grading job uses as the closing chance of each leg.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import SLIP_MENU, Pick, snai_bonus, solve
from scudi_slips.comps import ALWAYS, BY_NAME, COMPETITIONS, Comp, discovered, ordered
from scudi_slips.feed import price_feed

HOST = "https://api.the-odds-api.com/v4/sports"
CORE = [c.name for c in COMPETITIONS if c.group == "core"]
TOP5 = CORE[:5]
MIN_ODDS = 1.25
TARGETS = [25, 30, 40, 50]
COST = 2                      # markets x regions
RESERVE_PER_DAY = 7           # credits kept back per day to the monthly reset for the core and national pulls


class OutOfCredits(Exception):
    pass


def live_get(api_key: str):
    """GET a feed path; returns (parsed JSON, response headers). The key never leaves this function's closure."""
    def get(path: str, params: dict):
        q = urllib.parse.urlencode(dict(params, apiKey=api_key))
        req = urllib.request.Request(f"{HOST}{path}?{q}", headers={"User-Agent": "scudi/0.3"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8")), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 429) and "CREDITS" in body.upper():
                raise OutOfCredits(body) from e
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
    return get


def replay_get(events: dict[str, list], now: datetime):
    """The same interface over a recorded feed ({competition name: [events]}): every recorded competition is in season."""
    def get(path: str, params: dict):
        if path == "":
            return [{"key": BY_NAME[c].odds, "active": True, "has_outrights": False, "title": c} for c in events if c in BY_NAME], {}
        key = path.split("/")[1]
        name = next((c for c in events if c in BY_NAME and BY_NAME[c].odds == key), None)
        evs = events.get(name, []) if name else []
        lo, hi = params.get("commenceTimeFrom"), params.get("commenceTimeTo")
        if lo and hi:
            evs = [e for e in evs if lo <= e["commence_time"].replace("+00:00", "Z") <= hi]
        return evs, {}
    return get


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def window_end(now: datetime) -> datetime:
    """The next Tuesday or Friday 06:00 UTC at least 12 hours away."""
    for d in range(0, 10):
        t = (now + timedelta(days=d)).replace(hour=6, minute=0, second=0, microsecond=0)
        if t.weekday() in (1, 4) and t >= now + timedelta(hours=12):
            return t
    return now + timedelta(days=4)


def days_to_reset(now: datetime) -> int:
    nxt = (now.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((nxt - now).total_seconds() / 86400))


def affordable(comp: Comp, remaining: int | None, now: datetime) -> bool:
    if remaining is None:
        return True
    if remaining < COST:
        return False
    if comp.group in ALWAYS:
        return True
    return remaining - COST >= RESERVE_PER_DAY * days_to_reset(now)


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def in_season(get, names: list[str] | None) -> tuple[list[Comp], dict, str | None]:
    """The registry competitions the free sports list shows as active (plus national-team competitions it lists that the
    registry does not know). If the list cannot be read, every registry competition is tried: empty calls cost nothing."""
    wanted = [BY_NAME[n] for n in names if n in BY_NAME] if names else list(COMPETITIONS)
    try:
        sports, headers = get("", {})
    except OutOfCredits:
        raise
    except Exception as e:  # the list is a convenience, never a reason to stop
        return ordered(wanted), {}, f"sports list unavailable ({e}); trying every competition"
    active = {s.get("key") for s in sports if s.get("active")}
    comps = [c for c in wanted if c.odds in active]
    if not names:
        comps += [d for d in (discovered(s) for s in sports if s.get("active")) if d]
    return ordered(comps), headers, None


def core_end(now: datetime, end: datetime) -> datetime:
    """The weekend pull (window ending on a Tuesday) looks six days ahead for the core competitions."""
    return max(end, now + timedelta(days=6)) if end.weekday() == 1 else end


def pull(get, comps: list[Comp], now: datetime, end: datetime, remaining: int | None, end_core: datetime | None = None) -> dict:
    """One odds call per competition, cheapest-first order already applied; stops spending on the optional groups when
    the credits left no longer cover the reserve. Returns events, what was spent and skipped, and the last headers."""
    events, pulled, skipped, errors, meta = {}, [], {}, [], {}
    base = {"regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso", "commenceTimeFrom": iso(now)}
    for c in comps:
        params = dict(base, commenceTimeTo=iso(end_core if end_core and c.group == "core" else end))
        if not affordable(c, remaining, now):
            skipped[c.name] = "saving credits for the big leagues" if remaining is None or remaining >= COST else "no credits left"
            continue
        try:
            evs, headers = get(f"/{c.odds}/odds", params)
        except OutOfCredits:
            errors.append(f"{c.name}: out of credits")
            remaining = 0
            skipped[c.name] = "no credits left"
            continue
        except Exception as e:  # one competition failing must not lose the others
            errors.append(f"{c.name}: {e}")
            continue
        if headers.get("x-requests-remaining") is not None:
            remaining = _int(headers.get("x-requests-remaining"))
            meta = {"remaining": headers.get("x-requests-remaining"), "used": headers.get("x-requests-used")}
        spent = _int(headers.get("x-requests-last"))
        events[c.name] = evs
        pulled.append({"name": c.name, "matches": len(evs), "credits": spent if spent is not None else (COST if evs else 0)})
    return {"events": events, "pulled": pulled, "skipped": skipped, "errors": errors, "meta": meta, "remaining": remaining}


def sort_names(names, extra: list[Comp] | None = None) -> list[str]:
    known = {c.name: c for c in (extra or [])}
    known.update(BY_NAME)
    return [c.name for c in ordered([known.get(n) or Comp(n, "", None, "national", "") for n in names])]


def comp_info(names: list[str], extra: list[Comp] | None = None, old: list[dict] | None = None) -> list[dict]:
    """What the site and the other jobs need to know about each competition in the file."""
    known = {c.name: c for c in (extra or [])}
    known.update(BY_NAME)
    prev = {c["name"]: c for c in (old or [])}
    out = []
    for n in names:
        c = known.get(n)
        if c:
            out.append({"name": n, "group": c.group, "country": c.country, "espn": c.espn, "odds": c.odds})
        elif n in prev:
            out.append(prev[n])
        else:
            out.append({"name": n, "group": "national", "country": "", "espn": None, "odds": None})
    return out


def preset_slips(matches, now: datetime) -> list[dict]:
    """The standing slips, at every target, from what the feed allows; each is recorded so it can be graded later."""
    by_comp: dict[str, list] = {}
    for m in matches:
        by_comp.setdefault(m.competition, []).append(m)
    ucl = sorted(by_comp.get("Champions League", []), key=lambda m: m.kickoff)
    days = sorted({m.kickoff.date() for m in ucl})
    national = [m for m in matches if (BY_NAME.get(m.competition).group if m.competition in BY_NAME else "national") == "national"]
    presets = [("Serie A", by_comp.get("Serie A", []), 10), ("Top 5 leagues", [m for c in TOP5 for m in by_comp.get(c, [])], 10)]
    for d in days[:2]:
        presets.append((f"Champions League {d.strftime('%a')}", [m for m in ucl if m.kickoff.date() == d], 9))
    presets.append(("National teams", national, 10))
    if len(by_comp) >= 2 and len(matches) > max(len(p[1]) for p in presets):
        presets.append(("All competitions", list(matches), 10))
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


def carry_pending(old: dict, now: datetime, keep_days: float = 10.0) -> list[dict]:
    """The slips of the week being replaced, with the matches they use, so the grading job can still grade them if a
    full pull comes before it (a manual run, an empty week refilled midweek). Graded ones are skipped there by key."""
    out = [p for p in old.get("pending", []) if datetime.fromisoformat(p["built_at"]) >= now - timedelta(days=keep_days)]
    if old.get("slips") and old.get("built_at"):
        used = {p["match"] for s in old["slips"] for p in s["picks"]}
        out.append({"built_at": old["built_at"], "slips": old["slips"], "matches": [m for m in old.get("matches", []) if m["id"] in used]})
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
    """Core and national-team competitions with a kickoff in the next `hours`: the only ones a match-day pull refreshes."""
    end = now + timedelta(hours=hours)
    groups = {c["name"]: c.get("group") for c in week.get("competitions", [])}
    group = lambda n: BY_NAME[n].group if n in BY_NAME else groups.get(n, "national")
    return sorted({m["competition"] for m in week.get("matches", []) if now < datetime.fromisoformat(m["kickoff"]) <= end and group(m["competition"]) in ALWAYS})


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


def main(argv=None, get=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comps", nargs="*", help="only these competitions (default: every competition in season)")
    ap.add_argument("--mode", choices=["full", "late", "auto"], default="full")
    ap.add_argument("--late-hours", type=float, default=18.0, help="late mode: refresh competitions with a kickoff this soon")
    ap.add_argument("--window-days", type=float, help="full mode: a fixed window instead of 'to the next Tuesday or Friday 06:00 UTC'")
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
    if get is None:
        if a.from_file:
            get = replay_get(json.loads(Path(a.from_file).read_text()), now)
        else:
            key = os.environ.get("ODDS_API_KEY")
            if not key:
                sys.exit("ODDS_API_KEY is not set (keep it in a GitHub secret or a password manager, never in the code)")
            get = live_get(key)
    notes = []
    if mode == "late":
        due = comps_due(old, now, a.late_hours)
        if a.comps:
            due = [c for c in due if c in a.comps]
        if not due:
            print(f"late pull: no big-league or national-team kickoff in the next {a.late_hours:g} hours, nothing fetched, no credit spent")
            return 0
        known = {c["name"]: c for c in old.get("competitions", [])}
        comps = [BY_NAME[n] if n in BY_NAME else Comp(n, known[n]["odds"], known[n].get("espn"), "national", known[n].get("country", ""))
                 for n in due if n in BY_NAME or (n in known and known[n].get("odds"))]
        remaining = _int((old.get("credits") or {}).get("remaining"))
        end = now + timedelta(hours=a.late_hours)
        extra = [c for c in comps if c.name not in BY_NAME]
    else:
        comps, headers, note = in_season(get, a.comps)
        if note:
            notes.append(note)
        remaining = _int(headers.get("x-requests-remaining"))
        end = now + timedelta(days=a.window_days) if a.window_days else window_end(now)
        extra = [c for c in comps if c.name not in BY_NAME]
    wide = core_end(now, end) if mode == "full" and not a.window_days else end
    got = pull(get, comps, now, end, remaining, wide)
    end = max(end, wide)
    notes += got["errors"]
    if not got["events"] and got["errors"]:
        print("nothing could be pulled; the site keeps its current data:\n  " + "\n  ".join(notes))
        return 1
    matches, guard = price_feed(got["events"], now, end, need_sharp=a.need_sharp)
    fresh = [match_record(m) for m in matches]
    meta = got["meta"] or (old.get("credits", {}) if mode == "late" else {})
    if mode == "late":
        data = merge_late(old, fresh, [c.name for c in comps], now)
        data["credits"] = meta
        data["late_pull"] = {"at": now.isoformat(), "pulled": got["pulled"], "errors": got["errors"]}
        note = f"late pull of {', '.join(c.name for c in comps)}: {len(fresh)} upcoming matches refreshed, preset slips unchanged"
    else:
        slips = preset_slips(matches, now)
        names = sort_names({m["competition"] for m in fresh}, extra)
        data = {"built_at": now.isoformat(), "window_end": end.isoformat(), "window_days": round((end - now).total_seconds() / 86400, 2),
                "credits": meta, "guard": guard.__dict__, "competitions": comp_info(names, extra, old.get("competitions")),
                "pulled": got["pulled"], "skipped": got["skipped"], "notes": notes, "matches": fresh, "slips": slips,
                "pending": carry_pending(old, now)}
        note = f"{guard.kept} matches priced in {len(names)} competitions, {len(slips)} preset slips built"
    if mode == "late":
        data["competitions"] = comp_info(sort_names({m["competition"] for m in data.get("matches", [])}, extra), extra, old.get("competitions"))
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    history = add_snapshots(history, fresh, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    hist_path.write_text(json.dumps(history, separators=(",", ":"), ensure_ascii=False))
    spent = sum(p["credits"] or 0 for p in got["pulled"])
    print(f"{note} -> {out}; history: {len(history)} matches; credits spent {spent}, left {meta.get('remaining')}")
    print(f"  pulled: {', '.join(p['name'] + ' ' + str(p['matches']) for p in got['pulled']) or 'nothing'}")
    if got["skipped"]:
        print(f"  skipped: {got['skipped']}")
    for n in notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
