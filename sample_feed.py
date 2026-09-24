"""Write a synthetic odds feed for a whole matchweek (six competitions, several bookmakers) so the weekly job
and the site can be exercised without an API key. Fixtures: Serie A giornata 6 and Champions League matchday 2
(real lists, 10-14 October 2026); the other leagues' fixtures and every price are invented."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scudi_slips.matrix import score_matrix

FIX = {
 "Serie A": [("2026-10-10T13:00", "Genoa", "Fiorentina", 1.15, 1.20), ("2026-10-10T16:00", "Inter", "Parma", 2.35, 0.65), ("2026-10-10T18:45", "Napoli", "Frosinone", 2.20, 0.70),
             ("2026-10-11T10:30", "Como", "Roma", 1.35, 1.25), ("2026-10-11T13:00", "Lazio", "Monza", 1.85, 0.80), ("2026-10-11T13:00", "Lecce", "Bologna", 1.00, 1.30),
             ("2026-10-11T16:00", "Sassuolo", "Milan", 1.05, 1.75), ("2026-10-11T18:45", "Cagliari", "Juventus", 0.85, 1.60), ("2026-10-12T16:30", "Atalanta", "Venezia", 2.10, 0.80),
             ("2026-10-12T18:45", "Torino", "Udinese", 1.25, 1.05)],
 "Premier League": [("2026-10-10T11:30", "Liverpool", "Brentford", 2.30, 0.85), ("2026-10-10T14:00", "Man City", "Fulham", 2.40, 0.80), ("2026-10-10T14:00", "Chelsea", "Crystal Palace", 1.80, 1.00),
                    ("2026-10-10T16:30", "Tottenham", "Brighton", 1.60, 1.35), ("2026-10-11T13:00", "Newcastle", "Bournemouth", 1.75, 1.10), ("2026-10-11T15:30", "Aston Villa", "Everton", 1.65, 0.95)],
 "La Liga": [("2026-10-10T14:15", "Real Madrid", "Getafe", 2.30, 0.60), ("2026-10-10T19:00", "Barcelona", "Osasuna", 2.50, 0.75), ("2026-10-11T12:00", "Atletico Madrid", "Celta Vigo", 1.85, 0.85),
             ("2026-10-11T14:15", "Athletic Bilbao", "Valencia", 1.60, 0.85), ("2026-10-11T16:30", "Real Betis", "Sevilla", 1.45, 1.10), ("2026-10-11T19:00", "Real Sociedad", "Villarreal", 1.30, 1.25)],
 "Bundesliga": [("2026-10-10T13:30", "Bayern Munich", "Mainz", 2.90, 0.80), ("2026-10-10T13:30", "Borussia Dortmund", "Werder Bremen", 2.10, 1.10), ("2026-10-10T13:30", "Bayer Leverkusen", "Freiburg", 1.95, 1.00),
                ("2026-10-10T16:30", "RB Leipzig", "Wolfsburg", 1.90, 1.00), ("2026-10-11T13:30", "Stuttgart", "Borussia Monchengladbach", 1.95, 1.15), ("2026-10-11T15:30", "Eintracht Frankfurt", "Union Berlin", 1.75, 1.00)],
 "Ligue 1": [("2026-10-10T15:00", "Paris Saint Germain", "Nantes", 2.70, 0.65), ("2026-10-10T19:05", "Marseille", "Toulouse", 1.95, 0.95), ("2026-10-11T13:00", "Monaco", "Brest", 1.90, 1.00),
             ("2026-10-11T15:15", "Lille", "Rennes", 1.50, 1.05), ("2026-10-11T15:15", "Lyon", "Strasbourg", 1.70, 1.15), ("2026-10-11T18:45", "Lens", "Nice", 1.45, 1.05)],
 "Champions League": [("2026-10-13T16:45", "Lens", "Sporting CP", 1.30, 1.25), ("2026-10-13T16:45", "Sabah", "Slavia Praha", 0.95, 1.55), ("2026-10-13T19:00", "Arsenal", "Lille", 2.20, 0.75),
                      ("2026-10-13T19:00", "Atletico Madrid", "Manchester United", 1.55, 1.10), ("2026-10-13T19:00", "Inter", "Club Brugge", 2.05, 0.80), ("2026-10-13T19:00", "Galatasaray", "Barcelona", 1.20, 1.90),
                      ("2026-10-13T19:00", "RB Leipzig", "PSV", 1.75, 1.25), ("2026-10-13T19:00", "Viking", "Bayern Munich", 0.80, 2.60), ("2026-10-13T19:00", "Villarreal", "Napoli", 1.35, 1.30),
                      ("2026-10-14T16:45", "Feyenoord", "Como", 1.50, 1.15), ("2026-10-14T16:45", "LASK", "Liverpool", 0.75, 2.40), ("2026-10-14T19:00", "Roma", "Real Madrid", 1.20, 1.70),
                      ("2026-10-14T19:00", "Aston Villa", "Fenerbahce", 1.80, 0.95), ("2026-10-14T19:00", "Shakhtar Donetsk", "AEK Athens", 1.55, 1.00), ("2026-10-14T19:00", "Bodo/Glimt", "Borussia Dortmund", 1.45, 1.55),
                      ("2026-10-14T19:00", "Manchester City", "Paris Saint Germain", 1.70, 1.45), ("2026-10-14T19:00", "Real Betis", "Porto", 1.40, 1.15), ("2026-10-14T19:00", "Slovan Bratislava", "Stuttgart", 0.90, 1.85)],
}
BOOKS = [("pinnacle", 0.025), ("betfair_ex_eu", 0.02), ("unibet_eu", 0.055), ("williamhill", 0.062), ("betsson", 0.06), ("marathonbet", 0.05)]


def main(out="tests/feed_week_sample.json", seed=11):
    rng = random.Random(seed)
    feed = {}
    n = 0
    for comp, rows in FIX.items():
        evs = []
        for when, home, away, lh, la in rows:
            m = score_matrix(lh, la)
            ph = float(sum(m[h, a] for h in range(10) for a in range(10) if h > a))
            pd_ = float(sum(m[h, h] for h in range(10)))
            pa = float(sum(m[h, a] for h in range(10) for a in range(10) if h < a))
            po = float(sum(m[h, a] for h in range(10) for a in range(10) if h + a >= 3))
            books = []
            for key, margin in BOOKS:
                j = 1 + rng.uniform(-0.01, 0.01)
                books.append({"key": key, "title": key, "last_update": "2026-10-09T08:30:00Z", "markets": [
                    {"key": "h2h", "outcomes": [{"name": home, "price": round(j / (ph * (1 + margin)), 2)}, {"name": away, "price": round(j / (pa * (1 + margin)), 2)}, {"name": "Draw", "price": round(j / (pd_ * (1 + margin)), 2)}]},
                    {"key": "totals", "outcomes": [{"name": "Over", "price": round(j / (po * (1 + margin)), 2), "point": 2.5}, {"name": "Under", "price": round(j / ((1 - po) * (1 + margin)), 2), "point": 2.5}]}]})
            evs.append({"id": f"w{n:03d}", "sport_key": comp, "commence_time": when + ":00Z", "home_team": home, "away_team": away, "bookmakers": books})
            n += 1
        feed[comp] = evs
    Path(out).write_text(json.dumps(feed))
    print(n, "matches ->", out)


if __name__ == "__main__":
    main()
