"""Grade every slip the price job built, from final scores, and keep the running record.

    python3 -m tools.grade --week data/week.json --record data/record.json      # ESPN first; the odds feed only if needed
    python3 -m tools.grade --week ... --scores-file tests/scores_sample.json --now 2026-10-13T12:00:00Z   (replay)

Scores come from ESPN's public scoreboards first (free, no key: one request per competition covering the week's dates),
matched to the odds feed's matches by kickoff time and team names. Only matches ESPN cannot settle (a competition it
does not cover, a name it spells too differently) are asked of the odds feed's scores endpoint, 2 credits per
competition, results up to 3 days back (decision 74). Bets settle on 90 minutes: a match that went to extra time is
settled on its first two periods when ESPN lists them, else on the goals it lists up to 90'+stoppage, and left open
otherwise.
A slip is graded only when every leg's match has a final score; a slip with a postponed match stays open. The record
keeps, for every graded slip, the chance Scudi promised and whether it landed, so expected and actual hits can be
compared honestly over time. Slips of a week that a later full pull replaced ride along in week["pending"].
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips import settles
from scudi_slips.comps import BY_NAME
from scudi_slips.feed import SPORT_KEYS
from scudi_slips.matrix import view_from
from scudi_slips.picks import PICKS
from tools.teams import ALIASES, SITE, live_fetch, norm
from tools.weekly import closing

API = "https://api.the-odds-api.com/v4/sports/{key}/scores"
NATIONAL_ALIASES = {"czech republic": "czechia", "turkey": "turkiye", "ireland": "republic of ireland", "republic ireland": "republic of ireland",
                    "bosnia and herzegovina": "bosnia herzegovina", "korea republic": "south korea", "usa": "united states", "cote d ivoire": "ivory coast",
                    "macedonia": "north macedonia", "holland": "netherlands", "swiss": "switzerland"}


def fetch_scores(comps: list[str], api_key: str, days_from: int = 3) -> dict[str, dict]:
    scores = {}
    for comp in comps:
        q = urllib.parse.urlencode({"apiKey": api_key, "daysFrom": days_from, "dateFormat": "iso"})
        req = urllib.request.Request(API.format(key=SPORT_KEYS[comp]) + "?" + q, headers={"User-Agent": "scudi/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for ev in json.loads(r.read().decode("utf-8")):
                scores[ev["id"]] = ev
    return scores


def _key(name: str) -> str:
    k = norm(name).replace(" and ", " ")
    return NATIONAL_ALIASES.get(k) or ALIASES.get(k) or k


def same_team(a: str, b: str) -> int:
    """2 = the same name after normalising, 1 = one contains the other (4+ letters), 0 = different."""
    x, y = _key(a), _key(b)
    if x == y:
        return 2
    return 1 if min(len(x), len(y)) >= 4 and (x in y or y in x) else 0


def _espn_score(c: dict):
    sc = c.get("score")
    if isinstance(sc, dict):
        sc = sc.get("value", sc.get("displayValue"))
    try:
        return int(float(sc))
    except (TypeError, ValueError):
        return None


def _minute(display: str) -> int | None:
    """ESPN's clock text ("14'", "45'+3'") -> the minute before any stoppage time (45 for "45'+3'")."""
    try:
        return int(str(display).split("'")[0].split("+")[0])
    except ValueError:
        return None


# ESPN's names for a match that went past 90 minutes (the page uses the same list; "SUSPENDED" must not match "PEN")
ET_STATUS = re.compile(r"^STATUS_(FINAL_AET|FINAL_PEN|END_OF_REGULATION|END_OF_EXTRATIME|HALFTIME_ET|OVERTIME|SHOOTOUT|(FIRST_HALF_|SECOND_HALF_)?EXTRA_?TIME)$")


def espn_goals(ev: dict) -> list[tuple[str, int]] | None:
    """The goals ESPN lists for a match, as (side, minute), when they add up to its reported score. Shoot-out kicks are
    not goals; own goals are tried both ways, since ESPN may credit them to either side. None when they do not add up."""
    comp = (ev.get("competitions") or [{}])[0]
    sides = {str((c.get("team") or {}).get("id")): c.get("homeAway") for c in comp.get("competitors", [])}
    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in teams or "away" not in teams:
        return None
    reported = (_espn_score(teams["home"]), _espn_score(teams["away"]))
    plays = [d for d in comp.get("details") or [] if d.get("scoringPlay") and not d.get("shootout")]
    for flip in (False, True):
        out, ok = [], True
        for d in plays:
            side = sides.get(str((d.get("team") or {}).get("id")))
            minute = _minute((d.get("clock") or {}).get("displayValue", ""))
            if side is None or minute is None:
                ok = False
                break
            if flip and d.get("ownGoal"):
                side = "away" if side == "home" else "home"
            out.append((side, minute))
        if ok and (sum(g[0] == "home" for g in out), sum(g[0] == "away" for g in out)) == reported:
            return out
    return None


def espn_half(ev: dict, final: tuple[int, int] | None) -> tuple[int, int] | None:
    """The half-time score from the goals ESPN lists (scoring plays with their minute; first-half stoppage time counts as
    the first half), used only when those goals add up to the reported score. None when it cannot be told."""
    if final is None:
        return None
    goals = espn_goals(ev)
    if goals is None:
        return None
    first = [g for g in goals if g[1] <= 45]
    return sum(g[0] == "home" for g in first), sum(g[0] == "away" for g in first)


def espn_final(ev: dict) -> tuple[int, int] | None:
    """(home, away) after 90 minutes, or None if the match is not finished or its 90-minute score cannot be told.
    After extra time: the first two periods when ESPN lists them, else the goals up to 90'+stoppage when its goal list
    adds up (decision 80: a day's scoreboard often has no periods for these matches)."""
    comp = (ev.get("competitions") or [{}])[0]
    status = comp.get("status") or ev.get("status") or {}
    st = status.get("type") or {}
    if not st.get("completed"):
        return None
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    name = str(st.get("name", "")).upper()
    if ET_STATUS.match(name) or int(status.get("period") or 0) > 2:
        ls = [[_espn_score({"score": x.get("value", x.get("displayValue"))}) for x in (sides[k].get("linescores") or [])[:2]] for k in ("home", "away")]
        if all(len(v) == 2 and None not in v for v in ls):
            return sum(ls[0]), sum(ls[1])
        goals = espn_goals(ev)
        if goals is not None:
            reg = [g for g in goals if g[1] <= 90]
            return sum(g[0] == "home" for g in reg), sum(g[0] == "away" for g in reg)
        return None
    h, a = _espn_score(sides["home"]), _espn_score(sides["away"])
    return (h, a) if h is not None and a is not None else None


def _team_name(c: dict) -> str:
    t = c.get("team") or {}
    return t.get("displayName") or t.get("shortDisplayName") or t.get("name") or ""


def espn_finals(fetch, matches: list[dict], slugs: dict[str, str | None]) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Final scores from ESPN's scoreboards for the given matches: {match id: (home, away)}, plus notes."""
    finals, notes = {}, []
    by_comp: dict[str, list[dict]] = {}
    for m in matches:
        by_comp.setdefault(m["competition"], []).append(m)
    for comp, ms in by_comp.items():
        slug = slugs.get(comp)
        if not slug:
            notes.append(f"{comp}: no ESPN league, left to the odds feed")
            continue
        kicks = [datetime.fromisoformat(m["kickoff"]) for m in ms]
        lo, hi = min(kicks) - timedelta(days=1), max(kicks) + timedelta(days=1)
        url = f"{SITE.format(slug=slug)}/scoreboard?dates={lo:%Y%m%d}-{hi:%Y%m%d}&limit=300"
        board = None
        for u in (url, url.replace("https://site.web.api.espn.com/", "https://site.api.espn.com/", 1)):
            try:
                board = fetch(u)
                break
            except Exception as e:  # ESPN failing only means the odds feed is asked instead
                notes.append(f"{comp}: ESPN scoreboard failed ({e})")
        if board is None:
            continue
        events = board.get("events", []) if isinstance(board, dict) else []
        for m in ms:
            ko = datetime.fromisoformat(m["kickoff"])
            best, best_score = None, 0
            for ev in events:
                try:
                    t = datetime.fromisoformat(str(ev.get("date", "")).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if abs((t - ko).total_seconds()) > 3 * 3600:
                    continue
                sides = {c.get("homeAway"): _team_name(c) for c in (ev.get("competitions") or [{}])[0].get("competitors", [])}
                sh, sa = same_team(m["home"], sides.get("home", "")), same_team(m["away"], sides.get("away", ""))
                score = sh + sa if sh and sa else (1 if (sh == 2 or sa == 2) and abs((t - ko).total_seconds()) <= 600 else 0)
                if score > best_score:
                    best, best_score = ev, score
            if best is None:
                continue
            fs = espn_final(best)
            if fs is not None:
                ht = espn_half(best, fs)
                finals[m["id"]] = fs + ht if ht is not None else fs
    return finals, notes


def closing_chance(snap: dict, code: str) -> float | None:
    """A pick's chance in a price-history snapshot: stored directly for the classic picks, rebuilt from the snapshot's
    matrix for the others (decision 78)."""
    if code in snap.get("p", {}):
        return snap["p"][code]
    x = snap.get("x")
    if x and code in PICKS:
        return round(PICKS[code].chance(view_from(*x)), 4)
    return None


def final_score(ev: dict) -> tuple[int, int] | None:
    if not ev.get("completed"):
        return None
    got = {s["name"]: int(s["score"]) for s in ev.get("scores") or []}
    if ev["home_team"] not in got or ev["away_team"] not in got:
        return None
    return got[ev["home_team"]], got[ev["away_team"]]


def grade(week: dict, scores: dict[str, dict], record: dict, now: datetime, history: dict | None = None) -> dict:
    done = {s["key"] for s in record.get("slips", [])}
    finals = {mid: (tuple(ev) if isinstance(ev, (tuple, list)) else final_score(ev)) for mid, ev in scores.items()}
    comp_of = {m["id"]: m["competition"] for m in week.get("matches", [])}
    names = {m["id"]: f'{m["home"]} v {m["away"]}' for m in week.get("matches", [])}
    for slip in week.get("slips", []):
        key = f'{week["built_at"]}|{slip["name"]}|{slip["target"]}'
        if key in done:
            continue
        legs = []
        for p in slip["picks"]:
            fs = finals.get(p["match"])
            if fs is None or (p["code"] in PICKS and PICKS[p["code"]].half and len(fs) < 4):
                legs = None   # not finished yet, or a first-half pick whose half-time score is not known yet
                break
            won = settles(p["code"], *fs)
            leg = {"match": p["match"], "name": names.get(p["match"]), "competition": comp_of.get(p["match"]), "code": p["code"],
                   "chance": round(p["chance"], 4), "odds": p["odds"], "won": won, "score": f"{fs[0]}-{fs[1]}"}
            if len(fs) >= 4:
                leg["half"] = f"{fs[2]}-{fs[3]}"
            close = closing(history or {}, p["match"])
            cc = closing_chance(close, p["code"]) if close else None
            if cc is not None:
                leg["close_chance"] = cc
                leg["clv"] = round(p["odds"] * cc - 1, 4)   # >0: the price taken beat the last pre-kickoff view
            legs.append(leg)
        if legs is None:
            continue
        won = [x["won"] for x in legs]
        record.setdefault("slips", []).append({"key": key, "name": slip["name"], "target": slip["target"], "legs": slip["legs"],
                                               "chance": slip["chance"], "odds": slip["odds"], "bonus": slip["bonus"],
                                               "landed": all(won), "legs_won": sum(won), "graded_at": now.isoformat(), "leg_results": legs})
    graded = record.get("slips", [])
    exp = sum(s["chance"] for s in graded)
    record["summary"] = {"graded": len(graded), "expected_hits": round(exp, 2), "actual_hits": sum(s["landed"] for s in graded),
                         "by_name": {}}
    for s in graded:
        b = record["summary"]["by_name"].setdefault(s["name"], {"graded": 0, "expected": 0.0, "actual": 0})
        b["graded"] += 1
        b["expected"] = round(b["expected"] + s["chance"], 2)
        b["actual"] += int(s["landed"])
    return record


def weeks_of(week: dict, now: datetime | None = None) -> list[dict]:
    """The current week plus the ungraded weeks a later full pull replaced. Example data (a replay, or a week built after
    `now`) is never graded (decision 76)."""
    out = [week] + [{"built_at": p["built_at"], "matches": p.get("matches", []), "slips": p.get("slips", []), "example": p.get("example")}
                    for p in week.get("pending", [])]
    def real(w):
        if week.get("example") or w.get("example") or not w.get("built_at"):
            return False
        return now is None or datetime.fromisoformat(w["built_at"].replace("Z", "+00:00")) <= now
    return [w for w in out if real(w)]


def main(argv=None, fetch=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="data/week.json")
    ap.add_argument("--record", default="data/record.json")
    ap.add_argument("--scores-file", help="replay odds-feed scores instead of any network call")
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--no-espn", action="store_true", help="skip ESPN and use the odds feed's scores only")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    week = json.loads(Path(a.week).read_text())
    rec_path = Path(a.record)
    record = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    hist = json.loads(Path(a.history).read_text()) if Path(a.history).exists() else {}
    done = {s["key"] for s in record.get("slips", [])}
    wanted: dict[str, dict] = {}
    for w in weeks_of(week, now):
        ids = {p["match"] for s in w["slips"] if f'{w["built_at"]}|{s["name"]}|{s["target"]}' not in done for p in s["picks"]}
        wanted.update({m["id"]: m for m in w["matches"] if m["id"] in ids and datetime.fromisoformat(m["kickoff"]) < now})
    scores: dict = {}
    if a.scores_file:
        scores = {ev["id"]: ev for ev in json.loads(Path(a.scores_file).read_text())}
    elif wanted:
        slugs = {c["name"]: c.get("espn") for c in week.get("competitions", [])}
        slugs.update({n: c.espn for n, c in BY_NAME.items()})
        if not a.no_espn:
            finals, notes = espn_finals(fetch or live_fetch(pause=0.3), list(wanted.values()), slugs)
            scores.update(finals)
            for n in notes:
                print("  " + n)
            print(f"ESPN settled {len(finals)} of {len(wanted)} finished matches")
        left = sorted({m["competition"] for mid, m in wanted.items() if mid not in scores and m["competition"] in SPORT_KEYS})
        key = os.environ.get("ODDS_API_KEY")
        if left and key:
            try:
                got = fetch_scores(left, key)
                scores.update({mid: ev for mid, ev in got.items() if mid in wanted and mid not in scores})
                print(f"odds feed asked for {', '.join(left)} ({2 * len(left)} credits)")
            except Exception as e:  # the record simply waits for the next run
                print(f"odds feed scores failed: {e}")
        elif left:
            print(f"not settled and no odds key to ask: {', '.join(left)}")
    for w in weeks_of(week, now):
        record = grade(w, scores, record, now, hist)
    if "summary" not in record:
        record = grade({"built_at": "", "matches": [], "slips": []}, {}, record, now)
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
    print(record["summary"])


if __name__ == "__main__":
    main()
