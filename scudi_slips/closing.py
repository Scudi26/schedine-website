"""Closing prices at zero credits (decision 85).

football-data.co.uk publishes, within days of each round, one CSV per division and season with every match's result,
shots, cards, expected goals (HxG / AxG) and the bookmakers' opening AND closing prices: Betfair Exchange (BFEC...),
Bet365 (B365C...), the market average (AvgC...) and the best price (MaxC...) for 1 X 2 and over/under 2.5. Sixteen of
Scudi's competitions are covered. The grader takes the closing market from there, removes the margin, fits the score
matrix to it and prices every pick on a graded leg: CLV is then measured against a real closing price instead of the
morning pull (which ran 4-10 hours before kick-off). The Champions League, the other cups, national teams and the
leagues the files do not carry keep the last pre-kickoff pull as their closing view, flagged "last_pull".

    rows = ClosingSource().rows("Serie A", kickoff)          # one download per division and run
    row = find_row(rows, "AC Milan", "Lecce", kickoff)
    view, label, prices = closing_view(row)                  # fitted MarketView, "betfair" / "average" / "bet365"

The site at www.football-data.co.uk redirects to football-data.co.uk; urllib follows. Files are UTF-8 with a BOM.
Dates are dd/mm/yyyy in UK time; a match is matched on the same day or the day after the UTC kick-off, by team names.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta

from .devig import power_devig
from .matrix import MarketView, fit_market

URL = "https://football-data.co.uk/mmz4281/{season}/{div}.csv"
UA = "scudi/0.2 (personal accumulator builder; github.com/Scudi26)"

# Scudi competition -> football-data.co.uk division code. Not covered: Champions / Europa / Conference League, national
# teams, Austria, Switzerland, Denmark, Sweden, Norway (those five sit in a different file format, "new leagues", and
# carry no closing prices).
DIVISIONS = {"Serie A": "I1", "Premier League": "E0", "La Liga": "SP1", "Bundesliga": "D1", "Ligue 1": "F1",
             "Serie B": "I2", "Championship": "E1", "League One": "E2", "La Liga 2": "SP2", "2. Bundesliga": "D2", "Ligue 2": "F2",
             "Eredivisie": "N1", "Primeira Liga": "P1", "Belgian Pro League": "B1", "Süper Lig": "T1", "Scottish Premiership": "SC0",
             "Greek Super League": "G1"}

# football-data.co.uk spellings that the plain name matcher cannot pair with the odds feed's names (checked on the
# 2026-27 files, 5 Oct 2026: 313 of 337 feed names matched without help; these are the rest, plus a few safe ones).
FD_ALIASES = {
    "nott m forest": "nottingham forest", "nottm forest": "nottingham forest", "ath bilbao": "athletic club",
    "ath madrid": "atletico madrid", "espanol": "espanyol", "m gladbach": "borussia monchengladbach",
    "mgladbach": "borussia monchengladbach", "ein frankfurt": "eintracht frankfurt", "qpr": "queens park rangers",
    "sheffield weds": "sheffield wednesday", "sp gijon": "sporting gijon", "celta b": "celta fortuna",
    "sociedad b": "real sociedad b", "st etienne": "saint etienne", "for sittard": "fortuna sittard", "sp lisbon": "sporting cp",
    "guimaraes": "vitoria sc", "sp braga": "braga", "st truiden": "sint truiden", "st gilloise": "union saint gilloise",
    "buyuksehyr": "basaksehir", "erzurumspor": "erzurum bb", "aek": "aek athens", "levadeiakos": "levadiakos",
    "peterboro": "peterborough", "la coruna": "deportivo", "santander": "racing santander", "paris sg": "paris saint germain",
    "man united": "manchester united", "man city": "manchester city", "wolves": "wolverhampton wanderers",
    "west brom": "west bromwich albion", "sheffield united": "sheffield united", "milton keynes dons": "mk dons",
    "psv eindhoven": "psv", "den haag": "ado den haag", "nijmegen": "nec nijmegen", "standard": "standard liege",
    "waregem": "zulte waregem", "oud heverlee leuven": "oh leuven", "raal la louviere": "la louviere", "goztep": "goztepe",
    "volos nfc": "volos", "ofi crete": "ofi", "juve stabia": "juve stabia", "virtus entella": "entella", "hertha": "hertha berlin",
    "greuther furth": "greuther furth", "inter": "internazionale", "milan": "ac milan", "paris fc": "paris fc"}
# the odds feed's own spellings that differ from both (tools/teams.py's ALIASES cover the match page's cases)
FEED_ALIASES = {
    "inter milan": "internazionale", "inter": "internazionale", "milan": "ac milan", "atletico madrid": "atletico madrid",
    "athletic bilbao": "athletic club", "psg": "paris saint germain", "sporting lisbon": "sporting cp",
    "cercle brugge ksv": "cercle brugge", "union saint gilloise": "union saint gilloise", "sporting gijon": "sporting gijon",
    "racing de santander": "racing santander", "deportivo la coruna": "deportivo", "real sociedad": "real sociedad",
    "mk dons": "mk dons", "wolverhampton": "wolverhampton wanderers", "borussia dortmund": "dortmund",
    "bayer leverkusen": "leverkusen", "tsg hoffenheim": "hoffenheim", "fsv mainz 05": "mainz", "mainz 05": "mainz",
    "1 fc koln": "fc koln", "koln": "fc koln", "cologne": "fc koln", "vfb stuttgart": "stuttgart", "vfl wolfsburg": "wolfsburg",
    "fc augsburg": "augsburg", "sc freiburg": "freiburg", "sv elversberg": "elversberg", "hamburger sv": "hamburg",
    "sc paderborn": "paderborn", "1 fc union berlin": "union berlin", "sv werder bremen": "werder bremen", "fc st pauli": "st pauli",
    "olympique lyonnais": "lyon", "olympique marseille": "marseille", "as monaco": "monaco", "ogc nice": "nice",
    "losc lille": "lille", "stade rennais": "rennes", "stade brestois": "brest", "rc strasbourg": "strasbourg",
    "fc nantes": "nantes", "le havre ac": "le havre", "rc lens": "lens", "sco angers": "angers", "aj auxerre": "auxerre",
    "toulouse fc": "toulouse", "estac troyes": "troyes", "stade de reims": "reims", "fc metz": "metz",
    "as saint etienne": "saint etienne", "saint etienne": "saint etienne"}
_STOP = {"1909", "1913", "ac", "afc", "as", "bb", "bc", "ca", "calcio", "cd", "cf", "cfc", "club", "de", "fc", "fk", "kaa", "krc",
         "ksv", "kv", "og", "ol", "rc", "rcd", "rsc", "sc", "sco", "sd", "sk", "ss", "ssc", "sv", "tsg", "ud", "us", "vfb", "vfl"}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in _STOP)


def _canon(name: str) -> str:
    """One matching key for either spelling: both alias tables apply to both sides, so "Man City" (the feed and the
    file) and "Manchester City" (ESPN) meet at the same key."""
    k = _norm(name)
    k = FEED_ALIASES.get(k, FD_ALIASES.get(k, k))
    return _norm(FD_ALIASES.get(k, FEED_ALIASES.get(k, k)))


def fd_key(name: str) -> str:
    """A matching key for a football-data.co.uk spelling."""
    return _canon(name)


def feed_key(name: str) -> str:
    """A matching key for an odds-feed spelling."""
    return _canon(name)


def _same(a: str, b: str) -> int:
    if a == b:
        return 2
    return 1 if min(len(a), len(b)) >= 4 and (a in b or b in a) else 0


def season_code(when: datetime) -> str:
    """football-data.co.uk's season folder: 2627 for July 2026 - June 2027."""
    y = when.year if when.month >= 7 else when.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def parse_csv(text: str) -> list[dict]:
    return [r for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))) if r.get("HomeTeam") and r.get("Date")]


def _date(row: dict):
    try:
        d, m, y = row["Date"].split("/")
        return datetime(int(y) if len(y) == 4 else 2000 + int(y), int(m), int(d)).date()
    except (ValueError, AttributeError):
        return None


def find_row(rows: list[dict], home: str, away: str, kickoff: datetime) -> dict | None:
    """The CSV row of one match: on the kick-off's UTC day or the next one (UK time, late kick-offs), with both team
    names matched - exactly when possible, else one spelling inside the other; never an ambiguous pair."""
    days = {kickoff.date(), (kickoff + timedelta(days=1)).date(), (kickoff - timedelta(days=1)).date()}
    h, a = feed_key(home), feed_key(away)
    best, best_score = None, 0
    for r in rows:
        if _date(r) not in days:
            continue
        sh, sa = _same(h, fd_key(r["HomeTeam"])), _same(a, fd_key(r["AwayTeam"]))
        if not sh or not sa:
            continue
        score = sh + sa + (1 if _date(r) == kickoff.date() else 0)
        if score > best_score:
            best, best_score = r, score
        elif score == best_score:
            best = None if best is not r else best   # two rows fit equally well: trust neither
    return best


def _f(row: dict, key: str) -> float | None:
    try:
        v = float(row.get(key) or "")
        return v if v > 1.0 else None
    except ValueError:
        return None


def closing_prices(row: dict) -> tuple[dict, str] | None:
    """The closing 1 X 2 and over/under 2.5 prices of a row, from the sharpest column set that is complete:
    the Betfair Exchange, else the market average, else Bet365. Returns ({code: price}, label)."""
    for label, h, d, a, o, u in (("betfair", "BFECH", "BFECD", "BFECA", "BFEC>2.5", "BFEC<2.5"),
                                 ("average", "AvgCH", "AvgCD", "AvgCA", "AvgC>2.5", "AvgC<2.5"),
                                 ("bet365", "B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5")):
        p = {"1": _f(row, h), "X": _f(row, d), "2": _f(row, a), "O25": _f(row, o), "U25": _f(row, u)}
        if all(p[k] for k in ("1", "X", "2")):
            if not (p["O25"] and p["U25"]):   # a complete result market with the goals line from another column set
                for o2, u2 in (("BFEC>2.5", "BFEC<2.5"), ("AvgC>2.5", "AvgC<2.5"), ("B365C>2.5", "B365C<2.5"), ("MaxC>2.5", "MaxC<2.5")):
                    if _f(row, o2) and _f(row, u2):
                        p["O25"], p["U25"] = _f(row, o2), _f(row, u2)
                        break
            return {k: v for k, v in p.items() if v}, label
    return None


def closing_view(row: dict) -> tuple[MarketView, str, dict] | None:
    """The score matrix fitted to a row's closing market, margin removed (power), plus the label of the column set used
    and the raw closing prices. None when the row has no complete closing result market."""
    got = closing_prices(row)
    if not got:
        return None
    prices, label = got
    ph, pd_, pa = power_devig([prices["1"], prices["X"], prices["2"]])
    if prices.get("O25") and prices.get("U25"):
        po, _pu = power_devig([prices["O25"], prices["U25"]])
    else:
        # no closing goals line in the row: the matrix is fitted to a typical total and the label says so, so the grader
        # uses it for result picks only (a goals pick would be measured against an invented line)
        po, label = 0.52, label + "-no-goals-line"
    try:
        view = fit_market(ph, pd_, pa, po)
    except ValueError:
        return None
    return view, label, prices


def xg(row: dict) -> tuple[float, float] | None:
    try:
        return float(row["HxG"]), float(row["AxG"])
    except (KeyError, ValueError, TypeError):
        return None


class ClosingSource:
    """Downloads each division's season file once per run and finds matches in it. `fetch(url) -> text` can be replaced
    for tests; a failed download is remembered as None so the grader asks once."""

    def __init__(self, fetch=None):
        self.fetch = fetch or _live_fetch
        self.cache: dict[tuple[str, str], list[dict] | None] = {}
        self.notes: list[str] = []

    def covers(self, competition: str) -> bool:
        return competition in DIVISIONS

    def rows(self, competition: str, when: datetime) -> list[dict] | None:
        div = DIVISIONS.get(competition)
        if not div:
            return None
        key = (div, season_code(when))
        if key not in self.cache:
            try:
                self.cache[key] = parse_csv(self.fetch(URL.format(season=key[1], div=div)))
            except Exception as e:  # any failure: the leg waits for the next run
                self.cache[key] = None
                self.notes.append(f"{competition}: closing prices not downloaded ({e})")
        return self.cache[key]

    def find(self, competition: str, home: str, away: str, kickoff: datetime) -> dict | None:
        rows = self.rows(competition, kickoff)
        if not rows:
            return None
        return find_row(rows, home, away, kickoff)


def _live_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")
