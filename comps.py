"""Every competition Scudi can price, in one place (decision 74).

Each has the odds feed's sport key (The Odds API), ESPN's league slug (team data, live scores and grading, free) and a
group. The group decides two things: the order of the price pulls when credits run low, and whether the competition
gets a match-day refresh.

  core      the five big leagues and the Champions League: always pulled, refreshed on match days
  national  national teams (Nations League, qualifiers, World Cup, Euro): always pulled, refreshed on match days
  cups      Europa League and Conference League: pulled twice a week, no match-day refresh
  second    second divisions (and League One): pulled twice a week while credits allow
  europe    other European top flights: pulled twice a week while credits allow

Not available: the Ukrainian Premier League (not in the free odds feed) and the Polish Ekstraklasa (no ESPN data, so no
team pages and no free grading); both can be added here if that changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Comp:
    name: str
    odds: str            # The Odds API sport key
    espn: str | None     # ESPN league slug (site.web.api.espn.com/apis/site/v2/sports/soccer/{slug})
    group: str
    country: str


COMPETITIONS: list[Comp] = [
    Comp("Serie A", "soccer_italy_serie_a", "ita.1", "core", "Italy"),
    Comp("Premier League", "soccer_epl", "eng.1", "core", "England"),
    Comp("La Liga", "soccer_spain_la_liga", "esp.1", "core", "Spain"),
    Comp("Bundesliga", "soccer_germany_bundesliga", "ger.1", "core", "Germany"),
    Comp("Ligue 1", "soccer_france_ligue_one", "fra.1", "core", "France"),
    Comp("Champions League", "soccer_uefa_champs_league", "uefa.champions", "core", "Europe"),
    Comp("Nations League", "soccer_uefa_nations_league", "uefa.nations", "national", "Europe"),
    Comp("World Cup qualifiers", "soccer_fifa_world_cup_qualifiers_europe", "fifa.worldq.uefa", "national", "Europe"),
    Comp("Euro qualifiers", "soccer_uefa_euro_qualification", "uefa.euroq", "national", "Europe"),
    Comp("World Cup", "soccer_fifa_world_cup", "fifa.world", "national", "World"),
    Comp("Euro", "soccer_uefa_european_championship", "uefa.euro", "national", "Europe"),
    Comp("Europa League", "soccer_uefa_europa_league", "uefa.europa", "cups", "Europe"),
    Comp("Conference League", "soccer_uefa_europa_conference_league", "uefa.europa.conf", "cups", "Europe"),
    Comp("Serie B", "soccer_italy_serie_b", "ita.2", "second", "Italy"),
    Comp("Championship", "soccer_efl_champ", "eng.2", "second", "England"),
    Comp("League One", "soccer_england_league1", "eng.3", "second", "England"),
    Comp("La Liga 2", "soccer_spain_segunda_division", "esp.2", "second", "Spain"),
    Comp("2. Bundesliga", "soccer_germany_bundesliga2", "ger.2", "second", "Germany"),
    Comp("Ligue 2", "soccer_france_ligue_two", "fra.2", "second", "France"),
    Comp("Eredivisie", "soccer_netherlands_eredivisie", "ned.1", "europe", "Netherlands"),
    Comp("Primeira Liga", "soccer_portugal_primeira_liga", "por.1", "europe", "Portugal"),
    Comp("Belgian Pro League", "soccer_belgium_first_div", "bel.1", "europe", "Belgium"),
    Comp("Süper Lig", "soccer_turkey_super_league", "tur.1", "europe", "Turkey"),
    Comp("Scottish Premiership", "soccer_spl", "sco.1", "europe", "Scotland"),
    Comp("Austrian Bundesliga", "soccer_austria_bundesliga", "aut.1", "europe", "Austria"),
    Comp("Swiss Super League", "soccer_switzerland_superleague", "sui.1", "europe", "Switzerland"),
    Comp("Danish Superliga", "soccer_denmark_superliga", "den.1", "europe", "Denmark"),
    Comp("Allsvenskan", "soccer_sweden_allsvenskan", "swe.1", "europe", "Sweden"),
    Comp("Eliteserien", "soccer_norway_eliteserien", "nor.1", "europe", "Norway"),
    Comp("Greek Super League", "soccer_greece_super_league", "gre.1", "europe", "Greece"),
]
BY_NAME = {c.name: c for c in COMPETITIONS}
BY_KEY = {c.odds: c for c in COMPETITIONS}
GROUP_ORDER = ["core", "national", "cups", "second", "europe"]
ALWAYS = {"core", "national"}          # pulled whenever there is a credit left; refreshed on match days
FULL_TEAM_DATA = {"core"}              # lineups, match stats and transfers; the others get squads, results and tables

# national-team competitions the feed may list that are not in the registry (friendlies, a play-off): picked up by name
NATIONAL_HINTS = ("friendl", "nations_league", "world_cup_qualif", "euro_qualif")
NATIONAL_SKIP = ("women", "wom", "_u21", "_u20", "_u19", "_u17", "winner", "olympic")


def discovered(sport: dict) -> Comp | None:
    """A national-team competition the free sports list shows as active but the registry does not know (a friendlies
    window, a qualifying play-off). Outrights and youth or women's tournaments are left out."""
    key = str(sport.get("key", ""))
    if not key.startswith("soccer_") or key in BY_KEY or sport.get("has_outrights"):
        return None
    if any(s in key for s in NATIONAL_SKIP) or not any(h in key for h in NATIONAL_HINTS):
        return None
    espn = "fifa.friendly" if "friendl" in key else None
    return Comp(str(sport.get("title") or key), key, espn, "national", "World")


def ordered(comps: list[Comp]) -> list[Comp]:
    """Registry order within the group order: the order credits are spent in."""
    pos = {c.name: i for i, c in enumerate(COMPETITIONS)}
    return sorted(comps, key=lambda c: (GROUP_ORDER.index(c.group), pos.get(c.name, 999), c.name))


def site_list(names: list[str]) -> list[dict]:
    """What the site needs to know about the competitions in a data file: group, country, ESPN slug."""
    out = []
    for n in names:
        c = BY_NAME.get(n)
        out.append({"name": n, "group": c.group if c else "national", "country": c.country if c else "", "espn": c.espn if c else None})
    return out
