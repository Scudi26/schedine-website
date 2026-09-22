"""Turn a bookmaker odds feed (The Odds API v4 shape) into priced matches the slip builder can use.

Free plan: 500 credits a month; one call = markets × regions credits. We pull h2h + totals in the 'eu'
region (2 credits per competition per pull), which carries Pinnacle and the Betfair exchange (the sharp
reference) plus about two dozen ordinary books. SNAI is not in any feed: its prices are typed in by hand.

Guards (every one is counted in the report so a silent data problem shows up):
  * the match has not started, and is inside the window we build for
  * at least `min_books` usable books on the result market, at least one sharp book if `need_sharp`
  * books whose prices are stale (last_update older than max_age_hours) or inconsistent are dropped
  * the fitted score matrix reproduces the consensus (fit_error <= max_fit_error); otherwise the match is dropped
  * over/under picks are offered only when a 2.5 line is priced by enough books
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .comps import COMPETITIONS
from .consensus import SHARP_WEIGHTS, BookMarket, consensus, usable
from .matrix import fit_market
from .picks import PICKS, SLIP_MENU

SPORT_KEYS = {c.name: c.odds for c in COMPETITIONS}   # every competition the site can show (scudi_slips/comps.py)
DIRECT = {"1": ("h2h", "home"), "X": ("h2h", "draw"), "2": ("h2h", "away"), "O25": ("totals", "over"), "U25": ("totals", "under")}


@dataclass
class Guarded:
    kept: int = 0
    started: int = 0
    outside_window: int = 0
    too_few_books: int = 0
    no_sharp: int = 0
    bad_fit: int = 0
    no_totals: int = 0
    books_dropped: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PricedMatch:
    id: str
    competition: str
    kickoff: datetime
    home: str
    away: str
    chances: dict[str, float]          # fair chance of every pick in SLIP_MENU that can be offered
    estimate: dict[str, float]         # a typical ordinary-book price for each pick (median of ordinary books; derived where not quoted)
    best: dict[str, tuple[str, float]]  # best quoted price and the book quoting it, direct markets only
    books_used: int
    sharp_share: float
    fit_error: float
    lh: float = 0.0     # fitted expected goals, so the site can draw the score grid
    la: float = 0.0


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _floor2(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def price_event(ev: dict[str, Any], competition: str, now: datetime, window_end: datetime, g: Guarded, *, min_books: int = 2,
                need_sharp: bool = False, max_age_hours: float = 48.0, max_fit_error: float = 0.01) -> PricedMatch | None:
    kickoff = _parse_time(ev["commence_time"])
    if kickoff <= now:
        g.started += 1
        return None
    if kickoff > window_end:
        g.outside_window += 1
        return None
    home, away = ev["home_team"], ev["away_team"]
    h2h: list[BookMarket] = []
    tot: list[BookMarket] = []
    quotes: dict[str, dict[str, float]] = {k: {} for k in DIRECT}
    max_age = timedelta(hours=max_age_hours)
    for bk in ev.get("bookmakers", []):
        updated = _parse_time(bk["last_update"]) if bk.get("last_update") else None
        for mk in bk.get("markets", []):
            out = {o["name"]: o for o in mk.get("outcomes", [])}
            if mk["key"] == "h2h" and {home, away, "Draw"} <= set(out):
                m = BookMarket(bk["key"], [float(out[home]["price"]), float(out["Draw"]["price"]), float(out[away]["price"])], updated)
                h2h.append(m)
                if usable(m, now, max_age):                       # quotes from stale or broken books are never used as estimates
                    for code, side in (("1", 0), ("X", 1), ("2", 2)):
                        quotes[code][bk["key"]] = m.prices[side]
            elif mk["key"] == "totals":
                over = [o for o in mk.get("outcomes", []) if o["name"] == "Over" and float(o.get("point", -1)) == 2.5]
                under = [o for o in mk.get("outcomes", []) if o["name"] == "Under" and float(o.get("point", -1)) == 2.5]
                if over and under:
                    m = BookMarket(bk["key"], [float(over[0]["price"]), float(under[0]["price"])], updated)
                    tot.append(m)
                    if usable(m, now, max_age):
                        quotes["O25"][bk["key"]], quotes["U25"][bk["key"]] = m.prices
    c1 = consensus(h2h, now=now, max_age_hours=max_age_hours)
    if c1 is None or c1.books_used < min_books:
        g.too_few_books += 1
        return None
    if need_sharp and c1.sharp_share == 0:
        g.no_sharp += 1
        return None
    c2 = consensus(tot, now=now, max_age_hours=max_age_hours) if tot else None
    have_totals = c2 is not None and c2.books_used >= min_books
    if not have_totals:
        g.no_totals += 1
    g.books_dropped += c1.books_dropped + (c2.books_dropped if c2 else 0)
    p_over = c2.probs[0] if have_totals else _default_over(c1.probs)
    try:
        view = fit_market(c1.probs[0], c1.probs[1], c1.probs[2], p_over)
    except ValueError:
        g.bad_fit += 1
        return None
    if view.fit_error > max_fit_error:
        g.bad_fit += 1
        g.notes.append(f"{home} v {away}: fit error {view.fit_error:.3f}")
        return None
    ordinary = {code: [p for bk, p in qs.items() if bk not in SHARP_WEIGHTS] for code, qs in quotes.items()}
    est: dict[str, float] = {}
    for code in ("1", "X", "2"):
        est[code] = _median(ordinary[code] or list(quotes[code].values()))
    if have_totals:
        for code in ("O25", "U25"):
            est[code] = _median(ordinary[code] or list(quotes[code].values()))
    est["1X"] = _floor2(1 / (1 / est["1"] + 1 / est["X"]))
    est["X2"] = _floor2(1 / (1 / est["2"] + 1 / est["X"]))
    est["12"] = _floor2(1 / (1 / est["1"] + 1 / est["2"]))
    chances = {code: PICKS[code].chance(view) for code in SLIP_MENU}
    if have_totals:
        margin = 1 / est["O25"] + 1 / est["U25"] - 1
        for code, extra in (("O15", 0.01), ("U35", 0.01), ("GG", 0.015)):
            if code in chances:
                est[code] = max(1.01, _floor2(1 / (chances[code] * (1 + margin + extra))))
    else:
        for code in ("O15", "O25", "U25", "U35", "GG"):
            chances.pop(code, None)
    best = {code: max(qs.items(), key=lambda kv: kv[1]) for code, qs in quotes.items() if qs}
    g.kept += 1
    return PricedMatch(ev["id"], competition, kickoff, home, away, chances, est, best, c1.books_used, c1.sharp_share,
                       view.fit_error, view.lh, view.la)


def _default_over(p123: tuple[float, ...]) -> float:
    """No totals market: a bland over-2.5 chance so the result picks can still be used (goals picks are withheld)."""
    return 0.50


def price_feed(events_by_competition: dict[str, list[dict[str, Any]]], now: datetime, window_end: datetime,
               **kw) -> tuple[list[PricedMatch], Guarded]:
    g = Guarded()
    out: list[PricedMatch] = []
    for comp, events in events_by_competition.items():
        for ev in events:
            pm = price_event(ev, comp, now, window_end, g, **kw)
            if pm is not None:
                out.append(pm)
    out.sort(key=lambda m: (m.kickoff, m.competition, m.home))
    return out, g
