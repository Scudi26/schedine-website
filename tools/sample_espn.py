"""Synthetic ESPN-shaped responses for every team of the sample matchweek (tests/feed_week_sample.json), so
tools/teams.py can be exercised and tested without the network, and the site has example team data.

Shapes copy ESPN's real ones (teams list, roster, schedule, summary boxscore, core lineup, transactions) as read
in September 2026; every name, number and statistic here is invented ("example" is written into the output).

    python3 tools/sample_espn.py            # writes data/teams.json + data/players.json (example data for the site)
The tests call make() directly; the 3 MB of replayed responses are never written to disk.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.teams import FULL, LINEUP, LOGO, LOGO_DARK, SITE, SLUGS, TRANSFERS, WEB, build, find_team, replay_fetch

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "data" / "espn_teams.json").read_text())["competitions"]

FIRST = ["Luca", "Marco", "Andrea", "Matteo", "Lorenzo", "Nicolò", "Federico", "Davide", "Alessandro", "Riccardo", "Tomás", "Iker", "Pablo", "Álvaro", "Jonas", "Leon", "Niklas", "Florian",
         "Théo", "Hugo", "Kilian", "Amine", "Jonah", "Harry", "Ollie", "Mason", "Reece", "Kai", "Ben", "Declan", "Youssef", "Rafael", "João", "Diogo", "Mateo", "Tommaso", "Nicolás", "Enzo"]
LAST = ["Rossi", "Bianchi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci", "Marino", "Greco", "Conti", "García", "Martínez", "López", "Sánchez", "Müller", "Schmidt", "Fischer", "Weber",
        "Martin", "Bernard", "Dubois", "Moreau", "Smith", "Jones", "Taylor", "Brown", "Wilson", "Silva", "Santos", "Pereira", "Costa", "Fernández", "Kovač", "Novák", "Yilmaz", "Hansen"]
FORMATIONS = ["4-3-3", "4-2-3-1", "3-5-2", "3-4-2-1", "4-4-2", "4-3-1-2", "3-4-3"]
POS = [("G", "Goalkeeper", 3), ("D", "Defender", 8), ("M", "Midfielder", 7), ("F", "Forward", 5)]
NAT = {"Serie A": "Italy", "Premier League": "England", "La Liga": "Spain", "Bundesliga": "Germany", "Ligue 1": "France", "Champions League": "Portugal"}


def teams_of_week(feed: dict) -> dict[str, list[str]]:
    out = {}
    for comp, evs in feed.items():
        names = sorted({e["home_team"] for e in evs} | {e["away_team"] for e in evs})
        out[comp] = names
    return out


def make(feed: dict, seed: int = 11) -> dict:
    rnd = random.Random(seed)
    rec: dict[str, dict] = {}
    ids: dict[str, int] = {}
    real: dict[str, dict] = {}
    players_by_team: dict[int, list[dict]] = {}
    nxt = [90000]
    eids = [400000]
    everyone = [t for rows in REGISTRY.values() for t in rows]

    def tid(name):
        """The real ESPN id when the name is in the registry (so crests and colours are real), an invented one otherwise."""
        if name not in ids:
            hit = find_team(name, everyone)
            if hit:
                ids[name], real[name] = hit["id"], hit
            else:
                ids[name] = nxt[0]
                nxt[0] += 1
        return ids[name]

    def team_obj(name):
        i = tid(name)
        r = real.get(name) or {"name": name, "short": name.split(" ")[0] if len(name) > 14 else name, "abbr": name[:3].upper(), "color": f"{rnd.randrange(0x101010, 0xE0E0E0):06x}"}
        return {"id": str(i), "displayName": r["name"], "shortDisplayName": r["short"], "abbreviation": r["abbr"], "color": r["color"], "alternateColor": "ffffff",
                "logos": [{"href": LOGO.format(id=i), "rel": ["full", "default"]}, {"href": LOGO_DARK.format(id=i), "rel": ["full", "dark"]}]}

    for comp, names in teams_of_week(feed).items():
        slug = SLUGS[comp]
        rec[f"{SITE.format(slug=slug)}/teams"] = {"sports": [{"leagues": [{"teams": [{"team": team_obj(n)} for n in names]}]}]}
        for n in names:
            i = tid(n)
            if i not in players_by_team:
                squad, pid = [], i * 100
                for abbr, full, cnt in POS:
                    for _ in range(cnt):
                        pid += 1
                        age = rnd.randrange(18, 36)
                        squad.append({"id": str(pid), "displayName": f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", "shortName": None, "jersey": str(rnd.randrange(1, 99)),
                                      "weight": rnd.randrange(140, 200), "height": rnd.randrange(66, 78), "age": age, "dateOfBirth": f"{2026 - age}-0{rnd.randrange(1, 9)}-1{rnd.randrange(0, 9)}T08:00Z",
                                      "citizenship": NAT[comp] if rnd.random() < 0.6 else rnd.choice(list(NAT.values())), "flag": {"href": "https://example.invalid/flag.png"},
                                      "position": {"id": "1", "name": full, "displayName": full, "abbreviation": abbr}, "injuries": [{"status": "Out"}] if rnd.random() < 0.08 else [],
                                      "statistics": {"splits": {"categories": [{"name": "general", "stats": [{"name": "appearances", "value": rnd.randrange(0, 6)}, {"name": "yellowCards", "value": rnd.randrange(0, 3)}]},
                                                                                {"name": "offensive", "stats": [{"name": "totalGoals", "value": rnd.randrange(0, 4) if abbr in "MF" else 0}, {"name": "goalAssists", "value": rnd.randrange(0, 3)}]}]}}})
                for p in squad:
                    p["shortName"] = p["displayName"][0] + ". " + p["displayName"].split(" ")[1]
                players_by_team[i] = squad
            rec[f"{WEB.format(slug=slug)}/teams/{i}/roster"] = {"athletes": players_by_team[i]}
        # schedules: five finished rounds per competition, round robin among the week's teams
        base = datetime(2026, 8, 22, 18, 0, tzinfo=timezone.utc)
        events = {}
        order = names[:]
        for rnd_no in range(5):
            rnd.shuffle(order)
            for k in range(0, len(order) - 1, 2):
                h, a = order[k], order[k + 1]
                eids[0] += 1
                eid = str(eids[0])
                gh, ga = rnd.choice([0, 1, 1, 2, 2, 3]), rnd.choice([0, 0, 1, 1, 2])
                date = (base + timedelta(days=7 * rnd_no)).isoformat().replace("+00:00", "Z")
                ev = {"id": eid, "date": date, "competitions": [{"id": eid, "status": {"type": {"completed": True, "state": "post"}},
                                                                    "competitors": [{"id": str(tid(h)), "homeAway": "home", "score": {"value": gh, "displayValue": str(gh)}, "team": {"id": str(tid(h)), "displayName": team_obj(h)["displayName"]}},
                                                                                    {"id": str(tid(a)), "homeAway": "away", "score": {"value": ga, "displayValue": str(ga)}, "team": {"id": str(tid(a)), "displayName": team_obj(a)["displayName"]}}]}]}
                events.setdefault(h, []).append(ev)
                events.setdefault(a, []).append(ev)
                poss = rnd.randrange(35, 66)
                rec[f"{SITE.format(slug=slug)}/summary?event={eid}"] = {"boxscore": {"teams": [
                    {"team": {"id": str(tid(h)), "displayName": h}, "statistics": [{"name": "possessionPct", "displayValue": f"{poss}"}, {"name": "totalShots", "displayValue": str(rnd.randrange(6, 22))},
                                                                                   {"name": "shotsOnTarget", "displayValue": str(rnd.randrange(2, 9))}, {"name": "wonCorners", "displayValue": str(rnd.randrange(2, 11))},
                                                                                   {"name": "passPct", "displayValue": f"{rnd.randrange(70, 92)}"}, {"name": "tackles", "displayValue": str(rnd.randrange(8, 24))},
                                                                                   {"name": "interceptions", "displayValue": str(rnd.randrange(4, 16))}, {"name": "foulsCommitted", "displayValue": str(rnd.randrange(6, 18))}]},
                    {"team": {"id": str(tid(a)), "displayName": a}, "statistics": [{"name": "possessionPct", "displayValue": f"{100 - poss}"}, {"name": "totalShots", "displayValue": str(rnd.randrange(6, 22))},
                                                                                   {"name": "shotsOnTarget", "displayValue": str(rnd.randrange(2, 9))}, {"name": "wonCorners", "displayValue": str(rnd.randrange(2, 11))},
                                                                                   {"name": "passPct", "displayValue": f"{rnd.randrange(70, 92)}"}, {"name": "tackles", "displayValue": str(rnd.randrange(8, 24))},
                                                                                   {"name": "interceptions", "displayValue": str(rnd.randrange(4, 16))}, {"name": "foulsCommitted", "displayValue": str(rnd.randrange(6, 18))}]}]}}
                for side in (h, a):
                    squad = players_by_team[tid(side)]
                    form = rnd.choice(FORMATIONS)
                    gk = [p for p in squad if p["position"]["abbreviation"] == "G"][:1]
                    field = [p for p in squad if p["position"]["abbreviation"] != "G"]
                    rnd.shuffle(field)
                    xi = gk + sorted(field[:10], key=lambda p: "DMF".index(p["position"]["abbreviation"]))
                    entries = [{"playerId": int(p["id"]), "starter": True, "jersey": p["jersey"], "formationPlace": str(k + 1)} for k, p in enumerate(xi)]
                    entries += [{"playerId": int(p["id"]), "starter": False, "jersey": p["jersey"], "formationPlace": "0"} for p in field[10:14]]
                    rec[LINEUP.format(slug=slug, eid=eid, tid=tid(side))] = {"formation": {"summary": form, "name": form}, "entries": entries}
        for n in names:
            rec[f"{SITE.format(slug=slug)}/teams/{tid(n)}/schedule"] = {"events": events.get(n, [])}
    # transfers for every player
    all_teams = list(ids.items())
    for squad in players_by_team.values():
        for p in squad:
            hist = []
            year = 2026 - int(p["age"]) + 17
            club = rnd.choice(all_teams)
            for _ in range(rnd.randrange(0, 4)):
                year += rnd.randrange(1, 4)
                if year >= 2026:
                    break
                to = rnd.choice(all_teams)
                kind = rnd.choice(["Transfer", "Transfer", "Loan", "Free", "Undisclosed"])
                amt = rnd.choice([1.5, 4, 8, 12, 20, 35]) * 1e6 if kind == "Transfer" else 0.0
                hist.append({"date": f"{year}-0{rnd.randrange(1, 9)}-0{rnd.randrange(1, 9)}T07:00:00.000+00:00", "from": team_obj(club[0]), "to": team_obj(to[0]), "type": kind, "amount": amt,
                             "displayAmount": f"€{amt / 1e6:g}M" if amt else kind})
                club = to
            rec[TRANSFERS.format(pid=p["id"])] = {"transactions": hist}
    return rec


def main():
    feed = json.loads(Path("tests/feed_week_sample.json").read_text())
    rec = make(feed)
    print(f"{len(rec)} synthetic responses")
    teams, players, budget = build(replay_fetch(rec), FULL, {}, {}, datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
    teams["source"] = "example data: real teams, crests and colours; invented squads, results and transfers, in ESPN's shapes"
    players["source"] = teams["source"]
    Path("data/teams.json").write_text(json.dumps(teams, separators=(",", ":"), ensure_ascii=False))
    Path("data/players.json").write_text(json.dumps(players, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(teams['teams'])} teams, {len(players['players'])} players, {budget.calls} replayed requests -> data/teams.json, data/players.json")


if __name__ == "__main__":
    main()
