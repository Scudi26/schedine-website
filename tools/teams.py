"""Team and player data for the site, from ESPN's public site API (no key, no published limits, unofficial).

Writes data/teams.json (crests, squads, last lineup and formation, season averages such as possession and shots)
and data/players.json (transfer history with fees where ESPN shows them). Everything is public data; the job is
polite (one request every 0.25 s, a plain User-Agent) and incremental (matches and players already stored are not
fetched again).

    python3 tools/teams.py                                   # live, every competition with an ESPN league
    python3 tools/teams.py --comps "Serie A" --max-calls 400  # a smaller run
    python3 tools/teams.py --replay tests/espn_sample.json    # no network: replay recorded responses (the tests)

Not available from any free source, so not promised by the site: heatmaps, preferred foot, market values.

Two depths (decision 74): the big five leagues and the Champions League get everything (lineups and formations, match
stats such as possession, transfer histories); every other competition gets the light version (crests, squads,
results, form, home and away records, league tables) so the run stays polite and data/teams.json stays small.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips.comps import BY_NAME, COMPETITIONS, FULL_TEAM_DATA

SLUGS = {c.name: c.espn for c in COMPETITIONS if c.espn}
FULL = [c.name for c in COMPETITIONS if c.group in FULL_TEAM_DATA]
# site.api.espn.com sits behind Akamai and refuses some clients (it refused this project's sandbox and answers 403 to
# browsers); site.web.api.espn.com serves the same payloads to everyone, so it is tried first (decision 73).
SITE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/{slug}"
SITE_FALLBACK = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}"
WEB = SITE
TRANSFERS = "https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{pid}/transactions"
LINEUP = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{slug}/events/{eid}/competitions/{eid}/competitors/{tid}/roster"
STATS = {"possessionPct": "possession", "totalShots": "shots", "shotsOnTarget": "shots_on", "wonCorners": "corners", "passPct": "pass_pct",
         "tackles": "tackles", "interceptions": "interceptions", "foulsCommitted": "fouls", "saves": "saves"}
UA = "scudi/0.2 (personal accumulator builder; github.com/Scudi26)"


class Budget:
    """Counts requests and stops the run politely when the cap is reached."""

    def __init__(self, max_calls: int):
        self.max_calls, self.calls, self.failed = max_calls, 0, 0

    def spent(self) -> bool:
        return self.calls >= self.max_calls


def live_fetch(pause: float = 0.25):
    def get(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        time.sleep(pause)
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    return get


def replay_fetch(recorded: dict):
    def get(url: str):
        if url not in recorded:
            raise urllib.error.URLError(f"not recorded: {url}")
        return recorded[url]
    return get


def _get(fetch, budget: Budget, url: str, fallback: bool = True):
    if budget.spent():
        return None
    budget.calls += 1
    try:
        return fetch(url)
    except Exception as e:
        other = url.replace("https://site.web.api.espn.com/", "https://site.api.espn.com/", 1)
        if fallback and other != url:
            got = _get(fetch, budget, other, fallback=False)
            if got is not None:
                return got
        budget.failed += 1
        print(f"  ! {url.split('/apis/')[-1][:90]}: {e}")
        return None


def norm(name: str) -> str:
    """A matching key for a team name: no accents, no club words, no punctuation."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [w for w in s.split() if w not in {"fc", "ac", "as", "ss", "us", "cf", "sc", "afc", "ssc", "club", "calcio", "de", "1909", "1913", "cfc", "bc", "fk", "sv", "vfb", "vfl", "tsg", "sk", "rc", "og", "ol", "sco", "sd", "ud", "ca", "cd", "rcd"}]
    return " ".join(words)


def _num(s):
    try:
        return float(str(s).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _player(a: dict, slim: bool = False) -> dict:
    pos = a.get("position") or {}
    stats = {}
    for cat in ((a.get("statistics") or {}).get("splits") or {}).get("categories", []):
        for st in cat.get("stats", []):
            if st.get("name") in ("appearances", "subIns", "totalGoals", "goalAssists", "yellowCards", "redCards", "saves", "goalsConceded", "shotsOnTarget", "totalShots", "minutes"):
                stats[st["name"]] = _num(st.get("value"))
    out = {"id": int(a["id"]), "name": a.get("displayName") or a.get("fullName"), "short": a.get("shortName"), "jersey": a.get("jersey"),
           "pos": pos.get("abbreviation"), "posName": pos.get("displayName") or pos.get("name"), "age": a.get("age"),
           "dob": (a.get("dateOfBirth") or "")[:10] or None, "nat": a.get("citizenship"), "flag": ((a.get("flag") or {}).get("href")),
           "photo": ((a.get("headshot") or {}).get("href")), "injured": bool(a.get("injuries"))}
    if a.get("height"):
        out["height_cm"] = round(float(a["height"]) * 2.54)
    if a.get("weight"):
        out["weight_kg"] = round(float(a["weight"]) * 0.4536)
    if stats:
        out["stats"] = {k: v for k, v in stats.items() if v is not None and (v or not slim)}
    if slim:   # the light competitions: no photo or flag links, nothing empty
        out = {k: v for k, v in out.items() if k not in ("photo", "flag", "short") and v not in (None, "", {}, False)}
    return out


LOGO = "https://a.espncdn.com/i/teamlogos/soccer/500/{id}.png"
LOGO_DARK = "https://a.espncdn.com/i/teamlogos/soccer/500-dark/{id}.png"


def _logos(t: dict) -> dict:
    """ESPN's default crest and, when it lists one, the variant drawn for dark backgrounds (the site is dark)."""
    out = {}
    for lg in t.get("logos") or []:
        href = lg.get("href")
        if not href:
            continue
        if "dark" in href or "dark" in (lg.get("rel") or []):
            out.setdefault("logo_dark", href)
        else:
            out.setdefault("logo", href)
    if not out and t.get("logo"):
        out["logo"] = t["logo"]
    if not out and t.get("id"):
        out = {"logo": LOGO.format(id=t["id"]), "logo_dark": LOGO_DARK.format(id=t["id"])}
    return out


def _team_record(t: dict) -> dict:
    out = {"id": int(t["id"]), "name": t.get("displayName") or t.get("name"), "short": t.get("shortDisplayName") or t.get("name"),
           "abbr": t.get("abbreviation"), "color": t.get("color"), "alt": t.get("alternateColor")}
    out.update(_logos(t))
    return out


ALIASES = {"inter": "internazionale", "inter milan": "internazionale", "milan": "ac milan", "man city": "manchester city", "man united": "manchester united", "man utd": "manchester united",
           "psg": "paris saint germain", "bayern": "bayern munich", "atletico": "atletico madrid", "athletic": "athletic club", "athletic bilbao": "athletic club", "betis": "real betis",
           "celta": "celta vigo", "gladbach": "borussia monchengladbach", "dortmund": "borussia dortmund", "leverkusen": "bayer leverkusen", "leipzig": "rb leipzig", "frankfurt": "eintracht frankfurt",
           "werder": "werder bremen", "shakhtar": "shakhtar donetsk", "tottenham": "tottenham hotspur", "spurs": "tottenham hotspur", "brighton": "brighton hove albion", "wolves": "wolverhampton wanderers",
           "newcastle": "newcastle united", "west ham": "west ham united", "forest": "nottingham forest", "sporting": "sporting cp", "sporting lisbon": "sporting cp", "porto": "porto", "psv": "psv eindhoven",
           "juve": "juventus", "verona": "hellas verona", "slavia praha": "slavia prague", "fenerbahce": "fenerbahce", "bodo glimt": "bodo glimt", "lask": "lask linz", "viking": "viking fk", "sabah": "sabah"}


def find_team(name: str, teams: list[dict]) -> dict | None:
    """The team record whose name, short name or abbreviation matches a name from the odds feed (mirrors the site's findTeam)."""
    k = norm(name)
    cands = [c for c in (k, ALIASES.get(k)) if c]
    keys = lambda t: {norm(t.get("name", "")), norm(t.get("short", "")), norm(t.get("abbr", ""))} - {""}
    one = lambda hits: hits[0] if len({t.get("id") for t in hits}) == 1 else None   # the same club listed in two competitions is one hit
    for c in cands:
        hit = one([t for t in teams if c in keys(t)])
        if hit:
            return hit
    for c in cands:
        if len(c) < 4:
            continue
        hit = one([t for t in teams if any(len(x) >= 4 and (c in x or x in c) for x in keys(t))])
        if hit:
            return hit
    return None


def _formation_place(entry: dict) -> int:
    try:
        return int(entry.get("formationPlace") or 0)
    except (TypeError, ValueError):
        return 0


def _lineup(fetch, budget, slug: str, eid: str, tid: int):
    r = _get(fetch, budget, LINEUP.format(slug=slug, eid=eid, tid=tid))
    if not r:
        return None
    formation = ((r.get("formation") or {}).get("summary")) or ((r.get("formation") or {}).get("name"))
    xi = [{"id": int(e["playerId"]), "slot": _formation_place(e), "jersey": e.get("jersey")} for e in r.get("entries", []) if e.get("starter")]
    xi.sort(key=lambda x: x["slot"])
    return {"formation": formation, "xi": xi}


def build(fetch, comps: list[str], prev_teams: dict | None, prev_players: dict | None, now: datetime, max_calls: int = 5000,
          transfers: bool = True, print_every: int = 50) -> tuple[dict, dict, Budget]:
    budget = Budget(max_calls)
    prev_teams = prev_teams or {}
    prev_players = prev_players or {}
    teams: dict[str, dict] = {}
    seen_events: dict[str, set] = {}
    rostered: set[str] = set()
    for comp in comps:
        if comp not in SLUGS:
            print(f"{comp}: no ESPN league, skipped")
            continue
        slug = SLUGS[comp]
        lst = _get(fetch, budget, f"{SITE.format(slug=slug)}/teams")
        if not lst:
            continue
        entries = []
        for sport in lst.get("sports", []):
            for league in sport.get("leagues", []):
                entries.extend(x.get("team") or x for x in league.get("teams", []))
        print(f"{comp}: {len(entries)} teams")
        for t in entries:
            rec = _team_record(t)
            key = str(rec["id"])
            old = teams.get(key) or (prev_teams.get("teams", {}).get(key, {}) if isinstance(prev_teams.get("teams"), dict) else {})
            team = dict(old)   # a team in two competitions (Inter: Serie A and Champions League) keeps one record
            team.update(rec)
            team.setdefault("comps", [])
            if comp not in team["comps"]:
                team["comps"].append(comp)
            team.setdefault("sums", {"matches": 0, "events": [], "formations": {}, "goals_for": 0, "goals_against": 0, "wins": 0, "draws": 0, "losses": 0})
            teams[key] = team
            seen_events[key] = set(team["sums"]["events"])
        full = BY_NAME[comp].group in FULL_TEAM_DATA if comp in BY_NAME else False
        # squads (once per team per run, even when the team plays in two competitions)
        for t in entries:
            key = str(int(t["id"]))
            if key in rostered:
                continue
            r = _get(fetch, budget, f"{WEB.format(slug=slug)}/teams/{key}/roster")
            if r and r.get("athletes"):
                teams[key]["players"] = [_player(a, slim=not full and not teams[key].get("full")) for a in r["athletes"] if a.get("id")]
                rostered.add(key)
            if full:
                teams[key]["full"] = True
        # every finished match of every team, from the team schedules
        for t in entries:
            key = str(int(t["id"]))
            sched = _get(fetch, budget, f"{SITE.format(slug=slug)}/teams/{key}/schedule")
            if not sched:
                continue
            if not full:
                _results_from_schedule(teams[key], sched, key, comp)
                continue
            for ev in sched.get("events", []):
                eid = str(ev.get("id"))
                comp0 = (ev.get("competitions") or [{}])[0]
                done = ((comp0.get("status") or ev.get("status") or {}).get("type") or {}).get("completed")
                if not done or eid in seen_events.get(key, set()):
                    continue
                mine = next((c for c in comp0.get("competitors", []) if str((c.get("team") or c).get("id")) == key), None)
                other = next((c for c in comp0.get("competitors", []) if str((c.get("team") or c).get("id")) != key), None)
                if not mine or not other:
                    continue
                summ = _get(fetch, budget, f"{SITE.format(slug=slug)}/summary?event={eid}")
                if summ is None:
                    continue
                _absorb(teams[key], summ, eid, key, mine, other, ev.get("date"), comp)
                seen_events[key].add(eid)
                lu = _lineup(fetch, budget, slug, eid, int(key))
                if lu and lu["xi"]:
                    s = teams[key]["sums"]
                    if lu["formation"]:
                        s["formations"][lu["formation"]] = s["formations"].get(lu["formation"], 0) + 1
                    if not teams[key].get("last") or (ev.get("date") or "") >= teams[key]["last"].get("date", ""):
                        teams[key]["last"] = {"date": ev.get("date"), "event": eid, "formation": lu["formation"], "xi": lu["xi"]}
            if budget.calls % print_every < 3:
                print(f"  {budget.calls} requests so far", flush=True)
    # transfers: only players not stored yet
    players = dict(prev_players.get("players", {})) if isinstance(prev_players.get("players"), dict) else {}
    if transfers:
        wanted = [p["id"] for t in teams.values() if t.get("full") for p in t.get("players", []) if str(p["id"]) not in players]
        print(f"transfers to fetch: {len(wanted)}")
        for pid in wanted:
            if budget.spent():
                print("  request cap reached; the rest next run")
                break
            r = _get(fetch, budget, TRANSFERS.format(pid=pid))
            if r is None:
                continue
            players[str(pid)] = {"transfers": [_transfer(x) for x in r.get("transactions", [])]}
    out_teams = {"built_at": now.isoformat(), "source": "ESPN public site API (unofficial); logos and photos are ESPN's",
                 "competitions": {c: SLUGS[c] for c in comps if c in SLUGS}, "teams": {}, "tables": {}}
    for key, t in teams.items():
        out_teams["teams"][key] = _finish(t)
    out_teams["tables"] = tables(out_teams["teams"], [c for c in comps if c in SLUGS])
    out_players = {"built_at": now.isoformat(), "players": players}
    return out_teams, out_players, budget


def _score(c: dict):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("value", s.get("displayValue"))
    return _num(s)


def _blank_record() -> dict:
    return {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}


def _add_result(r: dict, gf: float, ga: float):
    r["p"] += 1
    r["gf"] += gf
    r["ga"] += ga
    r["w" if gf > ga else "d" if gf == ga else "l"] += 1


def _absorb(team: dict, summ: dict, eid: str, key: str, mine: dict, other: dict, date: str | None, comp: str | None = None):
    s = team["sums"]
    gf, ga = _score(mine), _score(other)
    if gf is not None and ga is not None:
        s["goals_for"] += gf
        s["goals_against"] += ga
        s["wins" if gf > ga else "draws" if gf == ga else "losses"] += 1
        home = mine.get("homeAway") == "home"
        if comp:
            c = s.setdefault("by_comp", {}).setdefault(comp, {"all": _blank_record(), "home": _blank_record(), "away": _blank_record()})
            _add_result(c["all"], gf, ga)
            _add_result(c["home" if home else "away"], gf, ga)
        team.setdefault("results", []).append({"date": (date or "")[:10], "event": eid, "vs": (other.get("team") or {}).get("displayName"),
                                               "vs_id": (other.get("team") or other).get("id"), "home": home, "gf": gf, "ga": ga, "comp": comp})
        team["results"] = sorted(team["results"], key=lambda r: r["date"])[-10:]
    for bt in (summ.get("boxscore") or {}).get("teams", []):
        if str((bt.get("team") or {}).get("id")) != key:
            continue
        for st in bt.get("statistics", []):
            name = STATS.get(st.get("name"))
            v = _num(st.get("displayValue"))
            if name and v is not None:
                s[name] = s.get(name, 0) + v
                s[name + "_n"] = s.get(name + "_n", 0) + 1
    s["matches"] += 1
    s["events"].append(eid)


def _results_from_schedule(team: dict, sched: dict, key: str, comp: str):
    """Light competitions: results, form and home/away records straight from the team schedule (scores included), rebuilt
    from scratch every run so nothing is counted twice."""
    rec = {"all": _blank_record(), "home": _blank_record(), "away": _blank_record()}
    res = [r for r in team.get("results", []) if r.get("comp") != comp]
    for ev in sched.get("events", []):
        comp0 = (ev.get("competitions") or [{}])[0]
        done = ((comp0.get("status") or ev.get("status") or {}).get("type") or {}).get("completed")
        mine = next((c for c in comp0.get("competitors", []) if str((c.get("team") or c).get("id")) == key), None)
        other = next((c for c in comp0.get("competitors", []) if str((c.get("team") or c).get("id")) != key), None)
        if not done or not mine or not other:
            continue
        gf, ga = _score(mine), _score(other)
        if gf is None or ga is None:
            continue
        home = mine.get("homeAway") == "home"
        _add_result(rec["all"], gf, ga)
        _add_result(rec["home" if home else "away"], gf, ga)
        res.append({"date": (ev.get("date") or "")[:10], "event": str(ev.get("id")), "vs": (other.get("team") or {}).get("displayName"),
                    "vs_id": (other.get("team") or other).get("id"), "home": home, "gf": gf, "ga": ga, "comp": comp})
    team["sums"].setdefault("by_comp", {})[comp] = rec
    team["results"] = sorted(res, key=lambda r: r["date"])[-10:]


def _transfer(x: dict) -> dict:
    f, t = x.get("from") or {}, x.get("to") or {}
    side = lambda d: dict({"id": d.get("id"), "name": d.get("displayName") or d.get("name")}, **_logos(d))
    return {"date": (x.get("date") or "")[:10], "from": side(f), "to": side(t), "type": x.get("type"), "amount": x.get("amount"), "fee": x.get("displayAmount")}


def tables(teams: dict, comps: list[str]) -> dict:
    """League tables built from the results the job stored: points, then goal difference, then goals scored.
    The Champions League table is its single league phase. Home and away records ride along for the match preview."""
    out = {}
    for comp in comps:
        rows = []
        for t in teams.values():
            rec = ((t.get("sums") or {}).get("by_comp") or {}).get(comp)
            if comp not in (t.get("comps") or []):
                continue
            rec = rec or {"all": _blank_record(), "home": _blank_record(), "away": _blank_record()}
            a = rec["all"]
            rows.append({"id": t["id"], "p": a["p"], "w": a["w"], "d": a["d"], "l": a["l"], "gf": int(a["gf"]), "ga": int(a["ga"]),
                         "pts": 3 * a["w"] + a["d"], "home": rec["home"], "away": rec["away"]})
        rows.sort(key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["id"]))
        for i, r in enumerate(rows):
            r["pos"] = i + 1
        out[comp] = rows
    return out


def _finish(t: dict) -> dict:
    s = t["sums"]
    n = s["matches"] or 0
    avg = {"matches": n}
    for k in ("possession", "shots", "shots_on", "corners", "pass_pct", "tackles", "interceptions", "fouls", "saves"):
        if s.get(k + "_n"):
            avg[k] = round(s[k] / s[k + "_n"], 1)
    if n:
        avg["goals_for"] = round(s["goals_for"] / n, 2)
        avg["goals_against"] = round(s["goals_against"] / n, 2)
        avg["record"] = f"{s['wins']}-{s['draws']}-{s['losses']}"
    else:   # a light competition: the season record from the stored results
        tot = [c["all"] for c in (s.get("by_comp") or {}).values()]
        p = sum(r["p"] for r in tot)
        if p:
            avg["matches"] = p
            avg["goals_for"] = round(sum(r["gf"] for r in tot) / p, 2)
            avg["goals_against"] = round(sum(r["ga"] for r in tot) / p, 2)
            avg["record"] = f"{sum(r['w'] for r in tot)}-{sum(r['d'] for r in tot)}-{sum(r['l'] for r in tot)}"
    forms = sorted(s.get("formations", {}).items(), key=lambda kv: -kv[1])
    out = {k: t[k] for k in ("id", "name", "short", "abbr", "color", "alt", "logo", "logo_dark", "comps", "full") if k in t}
    out["key"] = norm(t.get("name", ""))
    out["keys"] = sorted({norm(t.get("name", "")), norm(t.get("short", "")), norm(t.get("abbr", ""))} - {""})
    out["avg"] = avg
    out["form"] = "".join("W" if r["gf"] > r["ga"] else "D" if r["gf"] == r["ga"] else "L" for r in t.get("results", [])[-5:])
    out["results"] = t.get("results", [])[-5:]
    out["formation"] = forms[0][0] if forms else (t.get("last") or {}).get("formation")
    out["formations"] = dict(forms)
    if t.get("last"):
        out["last"] = t["last"]
    out["players"] = t.get("players", [])
    out["sums"] = s   # kept so the next run can continue the averages without refetching
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comps", nargs="*", default=list(SLUGS))
    ap.add_argument("--replay", help="a JSON file of {url: response} to replay instead of the network")
    ap.add_argument("--teams", default="data/teams.json")
    ap.add_argument("--players", default="data/players.json")
    ap.add_argument("--max-calls", type=int, default=5000)
    ap.add_argument("--no-transfers", action="store_true")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    fetch = replay_fetch(json.loads(Path(a.replay).read_text())) if a.replay else live_fetch()
    prev_t = json.loads(Path(a.teams).read_text()) if Path(a.teams).exists() else {}
    prev_p = json.loads(Path(a.players).read_text()) if Path(a.players).exists() else {}
    teams, players, budget = build(fetch, a.comps, prev_t, prev_p, now, max_calls=a.max_calls, transfers=not a.no_transfers)
    Path(a.teams).parent.mkdir(parents=True, exist_ok=True)
    Path(a.teams).write_text(json.dumps(teams, separators=(",", ":"), ensure_ascii=False))
    Path(a.players).write_text(json.dumps(players, separators=(",", ":"), ensure_ascii=False))
    n_pl = sum(len(t.get("players", [])) for t in teams["teams"].values())
    print(f"{len(teams['teams'])} teams, {n_pl} players, {len(players['players'])} transfer histories; {budget.calls} requests, {budget.failed} failed")
    print(f"wrote {a.teams} ({Path(a.teams).stat().st_size // 1024} KB) and {a.players} ({Path(a.players).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
